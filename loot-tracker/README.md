# Project Gorgon: Loot Tracker
These scripts are utilized to collect and track loot information to collect drops by mob type and drop rates.

# Requirements
1. WireShark must be installed. This is used to read packets to identify when loot windows are opened.
2. You must be a VIP in Project Gorgon so that you can save Chat Logs.

# Usage
1. Ensure you have saving of Chat Logs enabled in Project Gorgon under your VIP settings.
2. At the start of a play or looting session, run `ProjectGorgon-CapturePackets.ps1`. You may need to pass this the directory of `tshark.exe`, which is usually locationed wherever WireShark is installed.
3. Once finished, press enter to stop the capture script. It will export the results.
4. Run `ProjectGorgon-CollectLootData.ps1`. This will read your Chat Logs and any packet captures and output a CSV table of loot information.

Note: This may be run over multiple captures, and with multiple chat logs. It will compile all information into a single CSV based on your play session(s).