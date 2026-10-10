# BLOODBLINK Local Launcher

The Windows launcher starts the local development stack on this PC:

- PostgreSQL/PostGIS in the existing Ubuntu WSL distribution and BB-Core on port 8000, using `scripts/start-server.ps1`.
- The default BB-Console mode on port 5174.
- The hospital BB-Console mode on port 5175.
- It waits for the health endpoints, then opens both console URLs in the default browser.

Build output is a self-contained, single-file Windows x64 executable. It uses the existing repository, Node dependencies, Python installation, WSL database and local configuration; it does not copy patient data or environment files into the executable.

Double-clicking the executable starts services for that session. Closing the launcher stops only the web and API processes it started; PostgreSQL inside WSL may keep running. Services that were already running are reused and left alone. It does not add a Windows startup task, so after restarting the PC, double-click the launcher again.

By default it looks for `bloodblink` in the current Windows user's home directory. Set `BLOODBLINK_HOME` if the repository is elsewhere.

Build it from the repository root with:

```powershell
dotnet publish scripts\BloodBlinkLauncher\BloodBlinkLauncher.csproj -c Release -r win-x64 --self-contained true -o "$env:USERPROFILE\Downloads\BloodBlink-Local"
```
