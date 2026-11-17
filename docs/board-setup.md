# Board setup: SK-AM62B from a blank microSD card

How to get the TI SK-AM62B from a blank card to a board you can log into, record from, copy files to, and open a web page on. Every command here was run on the real board on 2026-11-03 (issue #1).

- Board: **SK-AM62B** (label on the PCB). AM62x, 4x Cortex-A53, 2 GB memory, no AI accelerator.
- Image: TI Processor SDK Linux AM62x **12.01.00.05.03** (Arago 2026.04, kernel 6.18.38-ti).
- Laptop used: Windows 11.

## 1. What you need

| Item | Notes |
|---|---|
| microSD card, 32 GB or more | SanDisk or Samsung. The image needs 17 GB; Linux grows to fill the card on first boot |
| USB-C power supply, 5 V / 3 A | Goes into **J11** |
| micro-USB **data** cable | Serial console, board **J15** to the laptop |
| Ethernet cable | Laptop to board, direct. Laptops without a port need a USB-C hub or adapter with Ethernet |
| USB hub with its own power | On the board's USB-A port: keyboard, mouse, mic |
| USB microphone | We use an Audio-Technica ATR2100-USB |
| HDMI monitor (optional) | HDMI port on the board only. USB-C does not carry video on this board |

## 2. Flash the card (on the laptop)

**Do not use balenaEtcher.** It failed three times (two cards, a Mac and a Windows laptop) with "The writer process ended unexpectedly" while decompressing the `.wic.xz`. Unpack first, then write with Raspberry Pi Imager.

1. Download `tisdk-default-image-am62xx-evm-12.01.00.05.03.rootfs.wic.xz` from https://www.ti.com/tool/download/PROCESSOR-SDK-LINUX-AM62X (no login). `am62xx-evm` is the image for the SK-AM62B.
2. Unpack it (Git Bash, WSL, or any `xz`):
   ```
   xz -dc tisdk-default-image-am62xx-evm-12.01.00.05.03.rootfs.wic.xz > tisdk-am62xx-evm-12.01.00.05.03.img
   ```
   Expected size: 18,257,075,200 bytes.
3. Raspberry Pi Imager: any device, **Use custom**, pick the `.img`, pick the card (check the size; never the laptop's own drive), **no** OS customisation, write, let it verify.
4. Check: re-insert the card. A drive named `boot` appears with `tiboot3.bin`, `tispl.bin`, `u-boot.img`, `Image`, `uEnv.txt`.

Windows offers "You need to format the disk" for every Linux card. Always click **Cancel**.

## 3. Connect the board

| Connector | Plug in | When |
|---|---|---|
| microSD slot | the flashed card | first |
| Boot switches | **SW2 = 01000000, SW1 = 11000010** (switch 1 to 8, 1 = ON); check against the silkscreen | before power |
| **J15** (micro-USB) | serial console to the laptop | before power |
| USB-A | powered hub with keyboard, mouse, mic | before power |
| RJ-45 (either port) | Ethernet cable to the laptop | any time |
| HDMI | monitor (optional) | before power |
| **J11** (USB-C, power only) | 5 V / 3 A supply | **last** |

J13 is the other USB-C port (power and data); leave it empty. The green LED that lights with only the micro-USB plugged in belongs to the serial chip; the board is off until J11 has power.

## 4. Serial console (Tera Term)

1. With J15 plugged in, Windows shows **4 new COM ports** (FTDI, PID 6011). The console is the **first one** (channel A; on our laptop COM12 of COM12 to COM15).
2. Tera Term: File, New connection, Serial, that port.
3. Setup, Serial port: **115200**, 8 bit, parity none, 1 stop bit, flow control none, **transmit delay 1 ms/char and 1 ms/line** (without it, pasted commands lose characters). Setup, Save setup.
4. Power the board. Garbled text means the speed is wrong (Tera Term starts at 9600).

## 5. First login

```
am62xx-evm login: root
```
No password. Then set one:
```
passwd
```

Record what you have:
```
cat /etc/os-release
uname -r
python3 --version
pip3 --version
python3 -c "import numpy, tflite_runtime; print('ml ok')"
free -h
df -h /
lsusb
```

Our results:

| Check | Result |
|---|---|
| `TISDK_VERSION` | 12.01.00.05.03 |
| Kernel | 6.18.38-ti |
| Python | 3.14.5 |
| pip | 26.0.1 |
| numpy, tflite_runtime | ml ok |
| Memory | 1.9 GiB total, 1.3 GiB available after boot, no swap |
| Storage | 28 GB, 17 GB free (on a 32 GB card) |

Also on the image: TFLite 2.20, ONNX Runtime 1.23.2 (C library only, no Python binding), `arecord`, `aplay`, `amixer`, `ffmpeg`, GStreamer, `gcc`, `g++`, `make`, `cmake`, `git`, Chromium, Weston, Docker, Dropbear SSH, `scp`, `sftp-server`, `hwclock`, `i2cdetect`. No PyTorch. No `nano`: the editor is `vi`.

## 6. Network: one cable, laptop to board

No router and no internet. Both sides give themselves a `169.254.x.x` (link-local) address.

1. Ethernet cable from the laptop (or its hub) to either RJ-45 port on the board.
2. Turn off any VPN on the laptop.
3. Wait about a minute, then on the board:
   ```
   ip -4 addr show
   ```
   Find `eth0` or `eth1` with `inet 169.254.x.x/16`. On our board it was `eth1`, `169.254.41.63`. The address can change; check each session.
4. On the laptop (PowerShell), check it answers:
   ```
   ping 169.254.41.63
   ```

If the laptop's internet came through that same cable, connect the laptop to Wi-Fi first.

## 7. SSH and copying files

Tera Term: File, New connection, TCP/IP, host = the board's address, SSH, port 22, user `root`. Or PowerShell:
```
ssh root@169.254.41.63
```
Pasting over SSH does not drop characters.

Copy a file from the board to the laptop (PowerShell on the laptop):
```
scp root@169.254.41.63:/root/mictest.wav $HOME\Downloads\
```
From the laptop to the board:
```
scp .\somefile root@169.254.41.63:/root/
```

## 8. Microphone

```
arecord -l
```
Our USB mic is **card 0** (`AT2005USB`). Card 1 is the board's own codec (the 3.5 mm jack).

Raise the mic's recording level and save it so it survives a reboot (the default 55% was too quiet):
```
amixer -c 0 sset Mic capture 90%
alsactl store
```

Record 3 seconds at the format the app and the model use (16 kHz, mono, 16-bit):
```
arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1 -d 3 /root/mictest.wav
```

Check the level without speakers:
```
python3 -c "import wave,numpy as n;w=wave.open('/root/mictest.wav');a=n.frombuffer(w.readframes(w.getnframes()),n.int16);print(w.getframerate(),'Hz',w.getnchannels(),'ch',round(len(a)/w.getframerate(),2),'s, peak',abs(a).max(),'of 32767')"
```
Good: a peak between about 2,000 and 30,000. Ours: `16000 Hz 1 ch 3.0 s, peak 3350`. The ATR2100 is a dynamic mic: speak 2 to 5 cm from it.

Then copy it to the laptop (section 7) and listen. Never commit recordings to this repo.

## 9. A page served by the board

On the board:
```
cd /root && python3 -m http.server 8000
```
On the laptop, open `http://169.254.41.63:8000` (type `http://`; some browsers switch to `https` and fail). Stop the server with Ctrl+C: it shares the whole folder.

## 10. Monitor (HDMI)

The image starts a desktop on HDMI by itself: `emptty` logs in the user `weston`, starts the Weston desktop, then TI's demo menu (`ti-apps-launcher`) opens on it.

If the monitor stays black or keeps cycling its inputs while `cat /sys/class/drm/*/status` says `connected`, the board is likely sending a mode the monitor rejects. Ours started at 1024x768 (it could not read the monitor's EDID at boot) and our portable monitor showed nothing. Force 1080p:
```
cp /etc/xdg/weston/weston.ini /etc/xdg/weston/weston.ini.bak
printf '\n[output]\nname=HDMI-A-1\nmode=1920x1080\n' >> /etc/xdg/weston/weston.ini
systemctl restart emptty
```
Set the monitor's input to HDMI by hand, not auto. Weston's log: `/var/log/emptty/session-errors.7.log`. Undo: copy the `.bak` file back.

TI's demo menu uses about 500 MB of memory (peak 830 MB of the 1.9 GB). Turn it off before timing models (#2):
```
systemctl stop ti-apps-launcher
systemctl disable ti-apps-launcher
```

## 11. Clock

The board has no battery-backed clock yet (an RTC module is planned), so after every power-on the date is wrong (ours said 13 March 2026). Set it by hand when it matters:
```
date -s "2026-11-03 22:45"
```

## 12. Shut down

```
poweroff
```
Wait for the console to stop, then unplug J11. Pulling power while Linux runs can damage the files on the card.

## 13. Known issues

| Symptom | Cause / fix |
|---|---|
| Etcher: "writer process ended unexpectedly" | Use the unpacked `.img` with Raspberry Pi Imager (section 2) |
| Garbled serial text | Tera Term speed is not 115200 |
| Pasted commands lose characters on serial | Transmit delay 1 ms/char (section 4), or use SSH |
| `aplay -D plughw:0,0` says "Device or resource busy" | Not investigated; recording is unaffected; play the file on the laptop instead |
| Kernel lines like `[ 145.6] bridge: filtering ...` appear in the console | Normal kernel messages (Docker's network bridge); press Enter |
| `fuser -v` fails | BusyBox `fuser` has no `-v` |
| Monitor black or cycling inputs, HDMI `connected` | Force 1920x1080 (section 10) |
| Wrong date | No RTC yet (section 11) |
