#!/usr/bin/env python3
"""
Analyze packet structure and field offsets across all identity packets.
This helps determine if offsets are fixed or variable.
"""

import sys
from collections import defaultdict

def analyze_packet_structure(hex_data: str):
    """
    Analyze a single packet and return its structure.
    """
    try:
        b = bytes.fromhex(hex_data)
        if len(b) < 12:
            return None
        
        msg_type = b[0:2].hex()
        if msg_type not in ("3f00", "3f01"):
            return None
        
        seq = int.from_bytes(b[2:4], "little")
        entity_id = int.from_bytes(b[4:8], "little")
        cookie = int.from_bytes(b[8:12], "little")
        cookie_hex = f"{cookie:08x}"
        
        # Skip chat messages (entity_id 20002)
        if entity_id == 20002:
            return None
        
        # Find all length-prefixed strings
        strings_with_offsets = []
        offset = 12
        
        while offset < len(b):
            if b[offset] == 0x00:
                offset += 1
                continue
            
            # Check if this looks like a length-prefixed string
            if offset + 1 < len(b):
                length = b[offset]
                if 1 <= length <= 64 and (offset + 1 + length) <= len(b):
                    val_bytes = b[offset+1 : offset+1+length]
                    try:
                        if all(32 <= c < 127 for c in val_bytes):
                            val = val_bytes.decode('ascii').strip()
                            # Skip competition IDs (long hex strings)
                            if not (len(val) >= 32 and all(c in '0123456789abcdefABCDEF ' for c in val)):
                                strings_with_offsets.append({
                                    'offset': offset,
                                    'length_byte': length,
                                    'string': val,
                                    'string_len': len(val),
                                    'next_offset': offset + 1 + length
                                })
                            offset = offset + 1 + length
                            continue
                    except:
                        pass
            offset += 1
        
        return {
            'msg_type': msg_type,
            'seq': seq,
            'entity_id': entity_id,
            'cookie': cookie_hex,
            'cookie_int': cookie,
            'packet_len': len(b),
            'strings': strings_with_offsets,
            'hex': hex_data
        }
    except Exception as e:
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_packet_offsets.py <logfile>")
        sys.exit(1)
    
    logfile = sys.argv[1]
    output_file = "analysis/offset_analysis.txt"
    
    # Open output file
    import os
    os.makedirs("analysis", exist_ok=True)
    out = open(output_file, "w", encoding="utf-8")
    
    def log(msg=""):
        print(msg)
        out.write(msg + "\n")
    
    log("="*80)
    log("PACKET OFFSET ANALYSIS")
    log("="*80)
    log(f"Analyzing: {logfile}")
    log()
    
    # Group packets by entity_id and packet_len
    packets_by_structure = defaultdict(list)
    offset_patterns = defaultdict(lambda: defaultdict(int))
    
    line_num = 0
    total_packets = 0
    
    with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            
            if not (line.startswith("3f00") or line.startswith("3f01")):
                continue
            
            line_num += 1
            result = analyze_packet_structure(line)
            
            if result:
                total_packets += 1
                entity_id = result['entity_id']
                packet_len = result['packet_len']
                
                # Group by structure type
                structure_key = f"entity_{entity_id}_len_{packet_len}"
                packets_by_structure[structure_key].append(result)
                
                # Track offset patterns
                for s in result['strings']:
                    offset = s['offset']
                    offset_patterns[structure_key][offset] += 1
    
    log(f"Total packets analyzed: {total_packets}")
    log(f"Unique structures found: {len(packets_by_structure)}")
    log()
    
    # Analyze each structure type
    for structure_key in sorted(packets_by_structure.keys()):
        packets = packets_by_structure[structure_key]
        entity_id = packets[0]['entity_id']
        packet_len = packets[0]['packet_len']
        
        log("="*80)
        log(f"STRUCTURE: {structure_key}")
        log("="*80)
        log(f"Entity ID: {entity_id}")
        log(f"Packet Length: {packet_len} bytes")
        log(f"Sample Count: {len(packets)}")
        log()
        
        # Analyze offset consistency
        log("OFFSET ANALYSIS:")
        log("-"*80)
        
        # Get all unique offsets used in this structure
        all_offsets = set()
        for pkt in packets:
            for s in pkt['strings']:
                all_offsets.add(s['offset'])
        
        for offset in sorted(all_offsets):
            count = offset_patterns[structure_key][offset]
            percentage = (count / len(packets)) * 100
            
            # Get sample strings at this offset
            sample_strings = []
            string_lengths = []
            for pkt in packets[:20]:  # Sample first 20
                for s in pkt['strings']:
                    if s['offset'] == offset:
                        sample_strings.append(s['string'])
                        string_lengths.append(s['string_len'])
                        break
            
            unique_samples = list(set(sample_strings))[:5]
            avg_len = sum(string_lengths) / len(string_lengths) if string_lengths else 0
            min_len = min(string_lengths) if string_lengths else 0
            max_len = max(string_lengths) if string_lengths else 0
            
            log(f"Offset {offset:3d}: Used in {count:4d}/{len(packets):4d} packets ({percentage:5.1f}%) | Len: {min_len}-{max_len} (avg {avg_len:.1f})")
            log(f"           Samples: {unique_samples}")
        
        log()
        
        # Show a few example packets
        log("EXAMPLE PACKETS:")
        log("-"*80)
        for i, pkt in enumerate(packets[:3], 1):
            log(f"Example {i}: Cookie {pkt['cookie']} | Seq {pkt['seq']}")
            for s in pkt['strings']:
                log(f"  Offset {s['offset']:3d}: '{s['string']}' (len={s['string_len']})")
            log()
        
        log()
    
    # Summary of findings
    log("="*80)
    log("SUMMARY")
    log("="*80)
    
    for structure_key in sorted(packets_by_structure.keys()):
        packets = packets_by_structure[structure_key]
        entity_id = packets[0]['entity_id']
        packet_len = packets[0]['packet_len']
        
        # Check if offsets are fixed
        offset_consistency = {}
        for offset in offset_patterns[structure_key]:
            count = offset_patterns[structure_key][offset]
            percentage = (count / len(packets)) * 100
            offset_consistency[offset] = percentage
        
        fixed_offsets = [o for o, p in offset_consistency.items() if p > 95]
        variable_offsets = [o for o, p in offset_consistency.items() if p <= 95]
        
        log(f"\n{structure_key}:")
        log(f"  Packets: {len(packets)}")
        log(f"  Fixed offsets (>95% consistent): {sorted(fixed_offsets)}")
        log(f"  Variable offsets (<=95%): {sorted(variable_offsets)}")
    
    log("\n" + "="*80)
    log(f"\nAnalysis saved to: {output_file}")
    out.close()


if __name__ == "__main__":
    main()
