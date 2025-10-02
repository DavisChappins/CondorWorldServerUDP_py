# Quick Start Guide - Condor Server Control Panel

## 🚀 Get Started in 3 Steps

### Step 1: Install Dependencies
```bash
pip install psutil
```

### Step 2: Start the Dashboard (as Administrator)
```bash
python app.py
```

### Step 3: Open Your Browser
Navigate to: **http://127.0.0.1:5001**

---

## 📝 First Time Setup

1. **Add Your First Server**
   - Scroll to the bottom of the dashboard
   - Enter a name: `My Condor Server`
   - Enter port: `56288`
   - Click "Add Server"

2. **Start Sniffing**
   - Click the green **Start** button
   - Watch the status LED turn green
   - Check for "Transmitting" status when packets arrive

3. **View Logs**
   - Log files are created with PID prefix
   - Example: `12345_udp_sniff_log_20251001_163000.txt`
   - All logs are in the same directory

---

## 🎯 Common Use Cases

### Running Multiple Servers
```
Server 1: Port 56288 (Main server)
Server 2: Port 56289 (Test server)
Server 3: Port 56290 (Backup server)
```

Each runs independently with its own PID and logs!

### Monitoring Status
- **Gray LED** = Stopped
- **Green LED (solid)** = Running, waiting for packets
- **Green LED (flashing)** = Actively receiving data
- **Red LED** = Error occurred

---

## ⚠️ Important Notes

- **Must run as Administrator** (Windows) or with `sudo` (Linux/Mac)
- Each server needs a **unique port**
- Ports must be between **1024-65535**
- Dashboard runs on port **5001** by default

---

## 🆘 Quick Troubleshooting

**Can't start dashboard?**
- Run as Administrator
- Check if port 5001 is available

**Server won't start?**
- Verify port is not in use
- Check `sniffAndDecodeUDP_toExpress_viaFlask.py` exists
- Ensure scapy is installed

**Status stuck on "Off"?**
- Check log files for errors
- Verify you have network capture permissions
- Try restarting the dashboard

---

## 📚 More Information

See `DASHBOARD_README.md` for complete documentation.

---

**Happy sniffing! 🎉**
