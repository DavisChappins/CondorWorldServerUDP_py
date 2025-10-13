#!/usr/bin/env python3
"""
Analyze field offset variability for entity_id=20001 packets.
Shows exact byte positions for each field across all packets.
"""

import sys
from collections import defaultdict

def analyze_packet_fields(hex_data: str):
    """
    Analyze a single packet and extract all field positions.
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
        
        # Only analyze entity_id=20001 (full player data)
        if entity_id != 20001:
            return None
        
        # Find all length-prefixed strings
        fields = []
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
                                if len(val) > 1:  # Filter single chars
                                    fields.append({
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
        
        # Assign field names based on position
        field_names = []
        if len(fields) >= 6:
            # Full packet: first_name, last_name, country, registration, cn, aircraft
            field_names = ['first_name', 'last_name', 'country', 'registration', 'cn', 'aircraft']
        elif len(fields) == 2:
            # Partial packet: cn, aircraft
            field_names = ['cn', 'aircraft']
        else:
            # Variable length
            field_names = [f'field_{i}' for i in range(len(fields))]
        
        # Build field mapping
        field_map = {}
        for i, field in enumerate(fields):
            if i < len(field_names):
                field_map[field_names[i]] = field
        
        return {
            'msg_type': msg_type,
            'seq': seq,
            'entity_id': entity_id,
            'cookie': cookie_hex,
            'cookie_int': cookie,
            'packet_len': len(b),
            'field_count': len(fields),
            'fields': field_map,
            'hex': hex_data
        }
    except Exception as e:
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_field_offsets.py <logfile>")
        sys.exit(1)
    
    logfile = sys.argv[1]
    output_file = "analysis/field_offset_variability.txt"
    
    import os
    os.makedirs("analysis", exist_ok=True)
    out = open(output_file, "w", encoding="utf-8")
    
    def log(msg=""):
        print(msg)
        out.write(msg + "\n")
    
    log("="*100)
    log("FIELD OFFSET VARIABILITY ANALYSIS")
    log("="*100)
    log(f"Analyzing: {logfile}")
    log()
    
    # Collect all packets
    packets = []
    
    with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or not (line.startswith("3f00") or line.startswith("3f01")):
                continue
            
            result = analyze_packet_fields(line)
            if result:
                packets.append(result)
    
    log(f"Total entity_id=20001 packets analyzed: {len(packets)}")
    log()
    
    # Group by field count
    by_field_count = defaultdict(list)
    for pkt in packets:
        by_field_count[pkt['field_count']].append(pkt)
    
    log("PACKETS BY FIELD COUNT:")
    log("-"*100)
    for count in sorted(by_field_count.keys()):
        log(f"  {count} fields: {len(by_field_count[count])} packets")
    log()
    
    # Analyze 6-field packets (complete player data)
    if 6 in by_field_count:
        complete_packets = by_field_count[6]
        log("="*100)
        log(f"COMPLETE PACKETS (6 fields) - {len(complete_packets)} packets")
        log("="*100)
        log()
        
        # Build offset table
        log("OFFSET VARIABILITY TABLE:")
        log("-"*100)
        log(f"{'Cookie':<12} {'first_name':<25} {'last_name':<25} {'country':<25} {'registration':<25} {'cn':<15} {'aircraft':<15}")
        log(f"{'':12} {'offset->len->next':<25} {'offset->len->next':<25} {'offset->len->next':<25} {'offset->len->next':<25} {'offset->len->next':<15} {'offset->len->next':<15}")
        log("-"*100)
        
        # Group by unique cookie to show all players
        by_cookie = {}
        for pkt in complete_packets:
            cookie = pkt['cookie']
            if cookie not in by_cookie:
                by_cookie[cookie] = pkt
        
        log(f"\nShowing all {len(by_cookie)} unique players:")
        log()
        
        # Show all unique players
        for cookie in sorted(by_cookie.keys()):
            pkt = by_cookie[cookie]
            fields = pkt['fields']
            
            def format_field(field_name):
                if field_name in fields:
                    f = fields[field_name]
                    return f"{f['offset']:3d}->{f['string_len']:2d}->{f['next_offset']:3d} '{f['string'][:8]}'"
                return "N/A"
            
            log(f"{cookie:<12} {format_field('first_name'):<25} {format_field('last_name'):<25} {format_field('country'):<25} {format_field('registration'):<25} {format_field('cn'):<15} {format_field('aircraft'):<15}")
        
        log()
        log("="*100)
        log("OFFSET STATISTICS FOR EACH FIELD")
        log("="*100)
        
        field_names = ['first_name', 'last_name', 'country', 'registration', 'cn', 'aircraft']
        
        for field_name in field_names:
            offsets = []
            lengths = []
            samples = []
            
            for pkt in complete_packets:
                if field_name in pkt['fields']:
                    f = pkt['fields'][field_name]
                    offsets.append(f['offset'])
                    lengths.append(f['string_len'])
                    if len(samples) < 10:
                        samples.append(f['string'])
            
            if offsets:
                min_offset = min(offsets)
                max_offset = max(offsets)
                unique_offsets = len(set(offsets))
                min_len = min(lengths)
                max_len = max(lengths)
                avg_len = sum(lengths) / len(lengths)
                
                log()
                log(f"FIELD: {field_name}")
                log(f"  Offset range: {min_offset} - {max_offset} (variability: {max_offset - min_offset} bytes)")
                log(f"  Unique offsets: {unique_offsets}")
                log(f"  String length: {min_len} - {max_len} (avg: {avg_len:.1f})")
                log(f"  Samples: {samples[:5]}")
                log(f"  Is offset fixed? {'YES' if unique_offsets == 1 else 'NO'}")
        
        log()
    
    # Analyze 2-field packets (partial data)
    if 2 in by_field_count:
        partial_packets = by_field_count[2]
        log("="*100)
        log(f"PARTIAL PACKETS (2 fields) - {len(partial_packets)} packets")
        log("="*100)
        log()
        
        log("OFFSET TABLE:")
        log("-"*100)
        log(f"{'Cookie':<12} {'cn':<30} {'aircraft':<30}")
        log(f"{'':12} {'offset->len->next':<30} {'offset->len->next':<30}")
        log("-"*100)
        
        for pkt in partial_packets[:20]:
            cookie = pkt['cookie']
            fields = pkt['fields']
            
            def format_field(field_name):
                if field_name in fields:
                    f = fields[field_name]
                    return f"{f['offset']:3d}->{f['string_len']:2d}->{f['next_offset']:3d} '{f['string']}'"
                return "N/A"
            
            log(f"{cookie:<12} {format_field('cn'):<30} {format_field('aircraft'):<30}")
        
        log()
    
    # NEW: Show fixed-offset parsing with full field content
    if 6 in by_field_count:
        complete_packets = by_field_count[6]
        log("="*100)
        log("FIXED-OFFSET PARSING TEST (reading full field content up to next offset)")
        log("="*100)
        log()
        
        # Get unique players
        by_cookie = {}
        for pkt in complete_packets:
            cookie = pkt['cookie']
            if cookie not in by_cookie:
                by_cookie[cookie] = pkt
        
        log(f"Testing fixed-offset parsing on {len(by_cookie)} unique players:")
        log("-"*100)
        
        for cookie in sorted(by_cookie.keys())[:10]:  # Show first 10
            pkt = by_cookie[cookie]
            hex_data = pkt['hex']
            b = bytes.fromhex(hex_data)
            
            # Read fields at fixed offsets, reading until next offset
            def read_fixed_field(start_offset, end_offset):
                """Read length-prefixed string at fixed offset."""
                if start_offset >= len(b):
                    return ""
                length = b[start_offset]
                if start_offset + 1 + length <= len(b):
                    return b[start_offset + 1 : start_offset + 1 + length].decode('ascii', errors='ignore').strip()
                return ""
            
            first_name = read_fixed_field(19, 36)
            last_name = read_fixed_field(36, 53)
            country = read_fixed_field(53, 70)
            registration = read_fixed_field(70, 78)
            cn = read_fixed_field(78, 189)
            aircraft = read_fixed_field(189, 224)
            
            log(f"Cookie {cookie}:")
            log(f"  first_name:   '{first_name}'")
            log(f"  last_name:    '{last_name}'")
            log(f"  country:      '{country}'")
            log(f"  registration: '{registration}'")
            log(f"  cn:           '{cn}'")
            log(f"  aircraft:     '{aircraft}'")
            log()
    
    log("="*100)
    log("CONCLUSION")
    log("="*100)
    log()
    log("If a field shows 'Is offset fixed? NO', it means the offset varies")
    log("based on the length of previous fields. This confirms that sequential")
    log("parsing (not fixed-offset parsing) is required for those fields.")
    log()
    log(f"Analysis saved to: {output_file}")
    
    out.close()


if __name__ == "__main__":
    main()
