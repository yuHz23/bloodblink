using System.Diagnostics;
using System.Drawing;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Windows.Forms;

namespace BloodBlinkLauncher;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LauncherForm());
    }
}

internal sealed class LauncherForm : Form
{
    private const int BackendPort = 8000;
    private const int CitizenPort = 5174;
    private const int HospitalPort = 5175;

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(2) };
    private readonly CancellationTokenSource _lifetime = new();
    private readonly Dictionary<string, Process> _ownedProcesses = new();
    private readonly Label _backendStatus = new();
    private readonly Label _citizenStatus = new();
    private readonly Label _hospitalStatus = new();
    private readonly Label _headline = new();
    private readonly TextBox _log = new();
    private readonly Button _stopButton = new();
    private bool _started;
    private string? _repoRoot;

    public LauncherForm()
    {
        Text = "BLOODBLINK Local";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(620, 470);
        Size = new Size(720, 560);
        BackColor = Color.FromArgb(250, 247, 240);
        Font = new Font("Segoe UI", 10F);

        BuildLayout();
        Shown += async (_, _) => await StartStackAsync();
        FormClosing += (_, _) =>
        {
            _lifetime.Cancel();
            StopOwnedProcesses();
        };
    }

    private void BuildLayout()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(22),
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 56));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 118));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        Controls.Add(root);

        var title = new Label
        {
            Text = "BLOODBLINK LOCAL",
            Dock = DockStyle.Fill,
            Font = new Font("Segoe UI", 18F, FontStyle.Bold),
            ForeColor = Color.FromArgb(139, 19, 35),
            TextAlign = ContentAlignment.MiddleLeft,
        };
        root.Controls.Add(title, 0, 0);

        _headline.Text = "Đang khởi động các dịch vụ local…";
        _headline.Dock = DockStyle.Fill;
        _headline.ForeColor = Color.FromArgb(34, 48, 71);
        _headline.TextAlign = ContentAlignment.MiddleLeft;
        root.Controls.Add(_headline, 0, 1);

        var statusPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12, 8, 12, 8),
            BackColor = Color.White,
        };
        for (var i = 0; i < 3; i++) statusPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 33.333F));
        SetStatus(_backendStatus, "BB-Core API · :8000", "Đang chờ");
        SetStatus(_citizenStatus, "Console · :5174", "Đang chờ");
        SetStatus(_hospitalStatus, "Console bệnh viện · :5175", "Đang chờ");
        statusPanel.Controls.Add(_backendStatus, 0, 0);
        statusPanel.Controls.Add(_citizenStatus, 0, 1);
        statusPanel.Controls.Add(_hospitalStatus, 0, 2);
        root.Controls.Add(statusPanel, 0, 2);

        _log.Dock = DockStyle.Fill;
        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.BackColor = Color.FromArgb(255, 253, 249);
        _log.Font = new Font("Consolas", 9F);
        root.Controls.Add(_log, 0, 3);

        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        var note = new Label
        {
            Text = "Đóng cửa sổ sẽ dừng web/API do launcher mở; PostgreSQL WSL có thể tiếp tục chạy.",
            Dock = DockStyle.Fill,
            ForeColor = Color.FromArgb(92, 101, 116),
            TextAlign = ContentAlignment.MiddleLeft,
        };
        footer.Controls.Add(note, 0, 0);

        _stopButton.Text = "Dừng dịch vụ";
        _stopButton.Dock = DockStyle.Fill;
        _stopButton.Enabled = false;
        _stopButton.BackColor = Color.FromArgb(139, 19, 35);
        _stopButton.ForeColor = Color.White;
        _stopButton.FlatStyle = FlatStyle.Flat;
        _stopButton.Click += (_, _) =>
        {
            _lifetime.Cancel();
            StopOwnedProcesses();
            SetHeadline("Đã dừng các dịch vụ do launcher khởi chạy.");
        };
        footer.Controls.Add(_stopButton, 1, 0);
        root.Controls.Add(footer, 0, 4);
    }

    private static void SetStatus(Label label, string service, string state)
    {
        label.Dock = DockStyle.Fill;
        label.TextAlign = ContentAlignment.MiddleLeft;
        label.ForeColor = Color.FromArgb(34, 48, 71);
        label.Text = $"●  {service} — {state}";
    }

    private async Task StartStackAsync()
    {
        if (_started) return;
        _started = true;
        var cancellationToken = _lifetime.Token;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            _repoRoot = ResolveRepoRoot();
            cancellationToken.ThrowIfCancellationRequested();
            if (_repoRoot is null)
            {
                SetHeadline("Không tìm thấy thư mục BLOODBLINK.");
                return;
            }

            var consoleDir = Path.Combine(_repoRoot, "bb-console");
            var viteEntry = Path.Combine(consoleDir, "node_modules", "vite", "bin", "vite.js");
            var serverScript = Path.Combine(_repoRoot, "scripts", "start-server.ps1");
            if (!File.Exists(viteEntry) || !File.Exists(serverScript))
                throw new InvalidOperationException("Thiếu dependencies hoặc scripts trong thư mục dự án.");

            await EnsureStartedAsync(
                "BB-Core API", "http://127.0.0.1:8000/api/health", BackendPort,
                () => StartBackend(serverScript), cancellationToken);
            await EnsureStartedAsync(
                "Console", "http://127.0.0.1:5174/", CitizenPort,
                () => StartVite(viteEntry, consoleDir, CitizenPort, hospitalMode: false), cancellationToken);
            await EnsureStartedAsync(
                "Console bệnh viện", "http://127.0.0.1:5175/", HospitalPort,
                () => StartVite(viteEntry, consoleDir, HospitalPort, hospitalMode: true), cancellationToken);

            cancellationToken.ThrowIfCancellationRequested();
            SetHeadline("Đã sẵn sàng. Đang mở hai console trong trình duyệt.");
            _stopButton.Enabled = _ownedProcesses.Count > 0;
            OpenBrowser("http://127.0.0.1:5174/");
            OpenBrowser("http://127.0.0.1:5175/");
        }
        catch (Exception ex)
        {
            if (ex is OperationCanceledException) return;
            SetHeadline("Khởi động chưa hoàn tất. Xem chi tiết bên dưới.");
            AppendLog("LỖI: " + ex.Message);
            _stopButton.Enabled = _ownedProcesses.Count > 0;
        }
    }

    private async Task EnsureStartedAsync(
        string name, string url, int port, Func<Process> start, CancellationToken cancellationToken)
    {
        SetServiceState(name, "Đang kiểm tra");
        if (!await IsReadyAsync(url, cancellationToken))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (await IsPortOpenAsync(port))
                throw new InvalidOperationException($"Cổng {port} đang được ứng dụng khác sử dụng.");

            cancellationToken.ThrowIfCancellationRequested();
            var process = start();
            _ownedProcesses[name] = process;
            AppendLog($"Đã khởi chạy {name}.");
        }
        else
        {
            AppendLog($"{name} đã chạy sẵn; dùng lại tiến trình hiện tại.");
        }

        SetServiceState(name, "Đang chờ sẵn sàng");
        for (var attempt = 0; attempt < 120; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (await IsReadyAsync(url, cancellationToken))
            {
                SetServiceState(name, "Đang chạy");
                return;
            }

            if (_ownedProcesses.TryGetValue(name, out var process) && process.HasExited)
                throw new InvalidOperationException($"{name} đã dừng với mã {process.ExitCode}.");

            await Task.Delay(1000, cancellationToken);
        }

        throw new TimeoutException($"{name} chưa sẵn sàng sau 120 giây.");
    }

    private Process StartBackend(string serverScript)
    {
        var powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            "WindowsPowerShell", "v1.0", "powershell.exe");
        var info = NewHiddenProcess(powershell, Path.GetDirectoryName(serverScript)!);
        info.ArgumentList.Add("-NoProfile");
        info.ArgumentList.Add("-ExecutionPolicy");
        info.ArgumentList.Add("Bypass");
        info.ArgumentList.Add("-File");
        info.ArgumentList.Add(serverScript);
        info.ArgumentList.Add("-Port");
        info.ArgumentList.Add(BackendPort.ToString());
        return StartTrackedProcess("BB-Core", info);
    }

    private Process StartVite(string viteEntry, string workingDirectory, int port, bool hospitalMode)
    {
        var info = NewHiddenProcess("node.exe", workingDirectory);
        info.ArgumentList.Add(viteEntry);
        if (hospitalMode)
        {
            info.ArgumentList.Add("--mode");
            info.ArgumentList.Add("hospital");
        }
        info.ArgumentList.Add("--host");
        info.ArgumentList.Add("127.0.0.1");
        info.ArgumentList.Add("--port");
        info.ArgumentList.Add(port.ToString());
        info.ArgumentList.Add("--strictPort");
        return StartTrackedProcess(hospitalMode ? "Console bệnh viện" : "Console", info);
    }

    private ProcessStartInfo NewHiddenProcess(string fileName, string workingDirectory) => new(fileName)
    {
        WorkingDirectory = workingDirectory,
        UseShellExecute = false,
        CreateNoWindow = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
    };

    private Process StartTrackedProcess(string name, ProcessStartInfo info)
    {
        var process = new Process { StartInfo = info, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) AppendLog($"[{name}] {e.Data}"); };
        process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) AppendLog($"[{name}] {e.Data}"); };
        if (!process.Start()) throw new InvalidOperationException($"Không khởi chạy được {name}.");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return process;
    }

    private async Task<bool> IsReadyAsync(string url, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.GetAsync(url, cancellationToken);
            if (response.StatusCode != HttpStatusCode.OK) return false;
            if (!url.EndsWith("/api/health", StringComparison.Ordinal)) return true;
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            return body.RootElement.TryGetProperty("status", out var status)
                && status.GetString() == "ok";
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return false;
        }
    }

    private static async Task<bool> IsPortOpenAsync(int port)
    {
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            await client.ConnectAsync("127.0.0.1", port);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private string? ResolveRepoRoot()
    {
        var configured = Environment.GetEnvironmentVariable("BLOODBLINK_HOME");
        if (IsRepoRoot(configured)) return Path.GetFullPath(configured!);

        var userRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "bloodblink");
        if (IsRepoRoot(userRoot)) return userRoot;

        var dialog = new FolderBrowserDialog
        {
            Description = "Chọn thư mục BLOODBLINK có scripts/start-server.ps1 và bb-console.",
            UseDescriptionForTitle = true,
        };
        return dialog.ShowDialog(this) == DialogResult.OK && IsRepoRoot(dialog.SelectedPath)
            ? dialog.SelectedPath
            : null;
    }

    private static bool IsRepoRoot(string? path) =>
        !string.IsNullOrWhiteSpace(path)
        && File.Exists(Path.Combine(path, "scripts", "start-server.ps1"))
        && Directory.Exists(Path.Combine(path, "bb-console"));

    private static void OpenBrowser(string url)
    {
        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    private void SetServiceState(string name, string state)
    {
        var label = name switch
        {
            "BB-Core API" => _backendStatus,
            "Console bệnh viện" => _hospitalStatus,
            _ => _citizenStatus,
        };
        if (InvokeRequired)
        {
            BeginInvoke(new Action(() => SetServiceState(name, state)));
            return;
        }
        label.Text = $"●  {name switch { "BB-Core API" => "BB-Core API · :8000", "Console bệnh viện" => "Console bệnh viện · :5175", _ => "Console · :5174" }} — {state}";
        label.ForeColor = state == "Đang chạy" ? Color.FromArgb(24, 131, 83) : Color.FromArgb(34, 48, 71);
    }

    private void SetHeadline(string text)
    {
        if (InvokeRequired)
        {
            BeginInvoke(new Action(() => SetHeadline(text)));
            return;
        }
        _headline.Text = text;
    }

    private void AppendLog(string line)
    {
        if (IsDisposed) return;
        if (InvokeRequired)
        {
            try { BeginInvoke(new Action(() => AppendLog(line))); } catch (InvalidOperationException) { }
            return;
        }
        _log.AppendText($"{DateTime.Now:HH:mm:ss}  {line}{Environment.NewLine}");
        if (_log.TextLength > 16000)
            _log.Text = _log.Text[^12000..];
    }

    private void StopOwnedProcesses()
    {
        foreach (var (name, process) in _ownedProcesses.Reverse())
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(5000);
                }
                AppendLog($"Đã dừng {name}.");
            }
            catch (Exception ex)
            {
                AppendLog($"Không dừng được {name}: {ex.Message}");
            }
            finally
            {
                process.Dispose();
            }
        }
        _ownedProcesses.Clear();
        _stopButton.Enabled = false;
    }
}
