using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("GEO 监测中心")]
[assembly: AssemblyProduct("GEO 监测中心")]
[assembly: AssemblyVersion("1.0.11.0")]

internal static class Launcher
{
    [STAThread]
    private static void Main()
    {
        try
        {
            string install = AppDomain.CurrentDomain.BaseDirectory;
            string app = Path.Combine(install, "app");
            string python = Path.Combine(install, "runtime", "pythonw.exe");
            string workerPython = Path.Combine(install, "runtime", "python.exe");
            string script = Path.Combine(app, "GEO-Monitor.pyw");
            string data = Environment.GetEnvironmentVariable("GEO_DATA_DIR");
            if (String.IsNullOrEmpty(data))
                data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GEO-Monitor");
            Directory.CreateDirectory(data);
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("软件文件不完整，请重新安装 GEO 监测中心。");
            var start = new ProcessStartInfo(python, "\"" + script + "\"");
            start.WorkingDirectory = app;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.EnvironmentVariables["GEO_RUNTIME_PYTHON"] = workerPython;
            start.EnvironmentVariables["GEO_DATA_DIR"] = data;
            if (String.IsNullOrEmpty(Environment.GetEnvironmentVariable("GEO_BROWSER_PORT")))
                start.EnvironmentVariables["GEO_BROWSER_PORT"] = "8093";
            start.EnvironmentVariables["PLAYWRIGHT_BROWSERS_PATH"] = Path.Combine(install, "browsers");
            start.EnvironmentVariables["PYTHONUTF8"] = "1";
            // Use only the bundled runtime; external Python settings must not break it.
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables.Remove("VIRTUAL_ENV");
            Process.Start(start);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "GEO 监测中心无法启动", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
