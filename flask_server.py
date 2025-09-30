from __future__ import annotations

import os
import time
import math
from typing import Dict, Any
from flask import Flask, request, jsonify, Response, render_template_string
from datetime import datetime, timezone


app = Flask(__name__)

# In-memory latest positions keyed by id (string)
# Each value is a list of recent position dicts, newest last.
# Each dict contains at least: id, lat, lon, updated_at (ISO), updated_ts (epoch seconds)
POSITIONS: Dict[str, list[Dict[str, Any]]] = {}
TRAIL_MAX_POINTS = 50

# Prune entries older than this TTL (seconds)
STALE_TTL_SEC = float(os.getenv("STALE_TTL_SEC", "30"))


def _coerce_float(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_stale() -> None:
    """Remove entries older than STALE_TTL_SEC."""
    if not POSITIONS:
        return
    now = time.time()
    now = time.time()
    stale_keys = []
    for k, trail in POSITIONS.items():
        if not trail: # handle empty trails
            stale_keys.append(k)
            continue
        # Check the timestamp of the newest point in the trail
        if (now - trail[-1].get("updated_ts", 0)) > STALE_TTL_SEC:
            stale_keys.append(k)

    for k in stale_keys:
        POSITIONS.pop(k, None)


@app.route("/api/position", methods=["POST"])
def api_position() -> Response:
    data = request.get_json(silent=True, force=False)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid JSON body"}), 400

    glider_id = data.get("id")
    if glider_id is None:
        return jsonify({"error": "missing id"}), 400
    glider_id = str(glider_id)

    raw_lat = data.get("lat")
    raw_lon = data.get("lon")
    lat_f = _coerce_float(raw_lat)
    lon_f = _coerce_float(raw_lon)

    if lat_f is None or lon_f is None:
        return jsonify({"error": "missing/invalid lat/lon"}), 400

    # Clamp to reasonable ranges
    lat_f = max(-90.0, min(90.0, lat_f))
    # Normalize lon into [-180, 180]
    lon_f = ((lon_f + 180.0) % 360.0) - 180.0

    # Store as floats to preserve numeric precision and consistency
    lat = lat_f
    lon = lon_f

    alt_m = _coerce_float(data.get("alt_m"))
    if alt_m is None:
        # accept alternate field name for convenience
        alt_m = _coerce_float(data.get("altitude_m"))

    heading_deg = _coerce_float(data.get("heading_deg"))
    if heading_deg is None:
        heading_deg = _coerce_float(data.get("heading"))
    if heading_deg is not None:
        heading_deg = (heading_deg % 360.0 + 360.0) % 360.0

    speed_mps = _coerce_float(data.get("speed_mps"))
    vario_mps = _coerce_float(data.get("vario_mps"))

    # Round for storage and downstream responses
    if alt_m is not None:
        alt_m = round(alt_m, 1)
    if heading_deg is not None:
        heading_deg = int(round(heading_deg))
    if speed_mps is not None:
        speed_mps = round(speed_mps, 2)
    if vario_mps is not None:
        vario_mps = round(vario_mps, 3)

    identity = (data.get("identity") or "").strip()
    aircraft = (data.get("aircraft") or "").strip()
    timestamp_client = (data.get("timestamp") or "").strip()
    
    # Extract individual identity fields
    id_aircraft = (data.get("id_aircraft") or "").strip()
    id_cn = (data.get("id_cn") or "").strip()
    id_reg = (data.get("id_reg") or "").strip()
    id_fname = (data.get("id_fname") or "").strip()
    id_lname = (data.get("id_lname") or "").strip()
    id_country = (data.get("id_country") or "").strip()

    now_iso = _now_iso_utc()
    now_ts = time.time()

    record = {
        "id": glider_id,
        "lat": lat,
        "lon": lon,
        "updated_at": now_iso,
        "updated_ts": now_ts,
    }
    if timestamp_client:
        record["timestamp"] = timestamp_client
    if alt_m is not None:
        record["alt_m"] = alt_m
    if heading_deg is not None:
        record["heading_deg"] = heading_deg
    if speed_mps is not None:
        record["speed_mps"] = speed_mps
    if vario_mps is not None:
        record["vario_mps"] = vario_mps
    if identity:
        record["identity"] = identity
    if aircraft:
        record["aircraft"] = aircraft
    if id_aircraft:
        record["id_aircraft"] = id_aircraft
    if id_cn:
        record["id_cn"] = id_cn
    if id_reg:
        record["id_reg"] = id_reg
    if id_fname:
        record["id_fname"] = id_fname
    if id_lname:
        record["id_lname"] = id_lname
    if id_country:
        record["id_country"] = id_country

    if glider_id not in POSITIONS:
        POSITIONS[glider_id] = []
    
    trail = POSITIONS[glider_id]
    trail.append(record)

    # Keep trail length at max TRAIL_MAX_POINTS
    if len(trail) > TRAIL_MAX_POINTS:
        POSITIONS[glider_id] = trail[-TRAIL_MAX_POINTS:]

    return ("", 204)


@app.route("/api/positions", methods=["GET"])
def api_positions() -> Response:
    _prune_stale()
    # Return as a list of the LATEST positions for simpler client handling
    out = []
    for trail in POSITIONS.values():
        if not trail: continue
        rec = trail[-1] # Get the latest position
        d = dict(rec)
        # Ensure lat/lon are numeric in the response (back-compat if older records stored strings)
        if "lat" in d:
            try:
                d["lat"] = float(d["lat"])
            except (TypeError, ValueError):
                pass
        if "lon" in d:
            try:
                d["lon"] = float(d["lon"])
            except (TypeError, ValueError):
                pass
        # Round numeric fields to reduce payload size
        if (v := d.get("alt_m")) is not None and isinstance(v, (int, float)):
            d["alt_m"] = round(float(v), 1)
        if (v := d.get("heading_deg")) is not None and isinstance(v, (int, float)):
            d["heading_deg"] = int(round(float(v)))
        if (v := d.get("speed_mps")) is not None and isinstance(v, (int, float)):
            d["speed_mps"] = round(float(v), 2)
        if (v := d.get("vario_mps")) is not None and isinstance(v, (int, float)):
            d["vario_mps"] = round(float(v), 3)
        out.append(d)
    return jsonify(out)


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Condor Live Map</title>
    <link
      rel="stylesheet"
      href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin=""
    />
    <style>
      html, body, #map { height: 100%; margin: 0; padding: 0; }
      .leaflet-container { background: #f0f0f0; }
      .info { position: absolute; top: 10px; left: 10px; background: white; padding: 6px 8px; border-radius: 4px; box-shadow: 0 0 5px rgba(0,0,0,0.2); }
      .glider-icon { width: 48px; height: 48px; transform-origin: 50% 50%; /* Rotate around center */ }
      .glider-wrap { width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; }
      .glider-label { font-size: 14px; font-family: sans-serif; font-weight: bold; fill: #000; stroke: #fff; stroke-width: 0.5px; paint-order: stroke; }
    </style>
  </head>
  <body>
    <div id="map"></div>
    <div class="info" id="info">Polling /api/positions…</div>
    <script
      src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
      integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
      crossorigin=""
    ></script>
    <script>
      const map = L.map('map').setView([20, 0], 2);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(map);

      const markers = {};
      const trails = {};
      const trailPts = {};
      const colors = {};
      function getLabel(identity) {
        if (!identity) return '';
        identity = identity.trim();
        const spaceIndex = identity.indexOf(' ');
        if (spaceIndex > 0) {
          return identity.substring(0, spaceIndex);
        }
        const cookieMatch = identity.match(/\[cookie\s+([a-f0-9]+)\]/);
        if (cookieMatch && cookieMatch[1]) {
          return cookieMatch[1].substring(0, 6); // Max 6 chars for cookie
        }
        if (spaceIndex === -1) {
          return identity;
        }
        return '';
      }

      function colorForId(id) {
        if (colors[id]) return colors[id];
        let h = 0;
        for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
        const hue = h % 360;
        const color = `hsl(${hue}, 85%, 50%)`;
        colors[id] = color;
        return color;
      }
      let didFit = false;

      function fmt(n, digits=5) { return (typeof n === 'number') ? n.toFixed(digits) : String(n); }
      function fmtAlt(m) { return (typeof m === 'number') ? m.toFixed(1) + ' m' : '—'; }
      function fmtSpd(v) { return (typeof v === 'number') ? v.toFixed(1) + ' m/s' : '—'; }
      function fmtHdg(h) { return (typeof h === 'number') ? h.toFixed(0) + '°' : '—'; }
      function fmtVario(v) { return (typeof v === 'number') ? v.toFixed(2) + ' m/s' : '—'; }

      function popupHtml(rec) {
        const id = rec.id || 'unknown';
        const ident = rec.identity ? ` - ${rec.identity}` : '';
        const ac = rec.aircraft ? `<div>Aircraft: ${rec.aircraft}</div>` : '';
        const ts = rec.updated_at ? new Date(rec.updated_at).toLocaleTimeString() : '';
        return `
          <div><b>${id}</b>${ident}</div>
          <div>Lat/Lon: ${rec.lat}, ${rec.lon}</div>
          <div>Alt: ${fmtAlt(rec.alt_m)} | Speed: ${fmtSpd(rec.speed_mps)} | Hdg: ${fmtHdg(rec.heading_deg)} | Vario: ${fmtVario(rec.vario_mps)}</div>
          ${ac}
          <div>Updated: ${ts}</div>
        `;
      }

      async function poll() {
        try {
          const res = await fetch('/api/positions');
          const data = await res.json();
          document.getElementById('info').textContent = `Gliders: ${data.length}`;

          const all_latlngs = [];
          const current_glider_ids = new Set();

          for (const rec of data) {
            const lat = parseFloat(rec.lat);
            const lon = parseFloat(rec.lon);
            if (isNaN(lat) || isNaN(lon)) continue;
            const id = String(rec.id || 'unknown');
            current_glider_ids.add(id);

            const ll = [lat, lon];
            const h = (typeof rec.heading_deg === 'number') ? rec.heading_deg : 0;
            const color = colorForId(id);
            const label = getLabel(rec.identity);
            const html = `
              <div class="glider-wrap">
                <svg class="glider-icon" viewBox="-24 -24 48 48" style="transform: rotate(${h}deg);">
                  <path d="M0 -10 L4 2 L0 0 L-4 2 Z" fill="${color}" stroke="#333" stroke-width="1.5"/>
                  <text x="0" y="14" class="glider-label" text-anchor="middle" dominant-baseline="middle" style="transform: rotate(${-h}deg);">${label}</text>
                </svg>
              </div>`;
            const icon = L.divIcon({ html, className: '', iconSize: [48,48], iconAnchor: [24,24] });

            if (!markers[id]) {
              const m = L.marker(ll, { icon });
              m.addTo(map);
              m.bindPopup(popupHtml(rec));
              markers[id] = m;
            } else {
              markers[id].setLatLng(ll);
              markers[id].setIcon(icon);
              markers[id].setPopupContent(popupHtml(rec));
            }

            // Update trail points, which are kept client-side
            if (!trailPts[id]) trailPts[id] = [];
            trailPts[id].push(ll);
            if (trailPts[id].length > 50) trailPts[id].shift();
            all_latlngs.push(...trailPts[id]);

            if (!trails[id]) {
              trails[id] = L.polyline(trailPts[id], { color, weight: 3, opacity: 0.8 }).addTo(map);
            } else {
              trails[id].setLatLngs(trailPts[id]);
              trails[id].setStyle({ color });
            }
          }

          // Prune markers and trails for gliders that are no longer present
          for (const id in markers) {
            if (!current_glider_ids.has(id)) {
              if (markers[id]) map.removeLayer(markers[id]);
              if (trails[id]) map.removeLayer(trails[id]);
              delete markers[id];
              delete trails[id];
              delete trailPts[id];
              delete colors[id];
            }
          }

          if (!didFit && all_latlngs.length > 0) {
            const bounds = L.latLngBounds(all_latlngs);
            map.fitBounds(bounds.pad(0.2));
            didFit = true;
          }
        } catch (e) {
          document.getElementById('info').textContent = 'Polling error';
          console.error('poll error', e);
        } finally {
          setTimeout(poll, 1000);
        }
      }

      poll();
    </script>
  </body>
</html>
"""


@app.route("/")
def index() -> Response:
    return render_template_string(INDEX_HTML)


def main():
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("FLASK_PORT", "5000"))
    except ValueError:
        port = 5000
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

