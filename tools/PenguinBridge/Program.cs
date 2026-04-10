using System.Reflection;
using System.Threading.Tasks;

static void FinishAsync(object? invokeResult)
{
    if (invokeResult is Task t)
        t.GetAwaiter().GetResult();
}

static int MainImpl(string[] args)
{
    if (args.Length < 5 || args[0] != "mgxc-to-c2s")
    {
        Console.Error.WriteLine("Usage: PenguinBridge mgxc-to-c2s --in <input.mgxc> --out <output.c2s>");
        return 2;
    }

    string? input = null;
    string? output = null;
    for (int i = 1; i < args.Length - 1; i++)
    {
        if (args[i] == "--in") input = args[i + 1];
        if (args[i] == "--out") output = args[i + 1];
    }

    if (string.IsNullOrWhiteSpace(input) || string.IsNullOrWhiteSpace(output))
    {
        Console.Error.WriteLine("Missing --in or --out");
        return 2;
    }

    var inPath = Path.GetFullPath(input);
    var outPath = Path.GetFullPath(output);
    if (!File.Exists(inPath))
    {
        Console.Error.WriteLine($"Input not found: {inPath}");
        return 3;
    }

    try
    {
        EnsurePenguinToolsCoreLoaded();

        // 使用反射避免编译期强绑定具体 API 细节；只要 PenguinTools.Core 提供 MgxcParser + C2SConverter 即可。
        var coreAsm = AppDomain.CurrentDomain.GetAssemblies()
            .FirstOrDefault(a => a.GetName().Name == "PenguinTools.Core");
        if (coreAsm is null)
        {
            Console.Error.WriteLine(
                "PenguinTools.Core is not loaded. Build PenguinBridge with PenguinTools.Core as a project reference, "
                + "or place PenguinTools.Core.dll next to PenguinBridge.exe, or set CHUNI_PENGUIN_TOOLS_CORE_DLL.");
            return 4;
        }

        var diagType = coreAsm.GetType("PenguinTools.Core.Diagnoster");
        var parserType = coreAsm.GetType("PenguinTools.Core.Chart.Parser.MgxcParser");
        var convType = coreAsm.GetType("PenguinTools.Core.Chart.Converter.C2SConverter");
        if (diagType is null || parserType is null || convType is null)
        {
            Console.Error.WriteLine("Required PenguinTools.Core types not found.");
            return 5;
        }

        var diag = Activator.CreateInstance(diagType);
        if (diag is null) return 6;

        var parser = Activator.CreateInstance(parserType, diag, null);
        if (parser is null) return 7;
        parserType.GetProperty("Path")?.SetValue(parser, inPath);

        // PenguinTools 的 MgxcParser 需要 AssetManager（与 GUI 一致：硬资产 JSON 流）。
        var assetMgrType = coreAsm.GetType("PenguinTools.Core.Asset.AssetManager");
        if (assetMgrType is not null)
        {
            var assetsPath = Path.Combine(AppContext.BaseDirectory, "assets.json");
            if (!File.Exists(assetsPath))
            {
                Console.Error.WriteLine(
                    "assets.json not found next to PenguinBridge.exe (expected from PenguinTools GUI Resources). "
                    + $"Looked for: {assetsPath}");
                return 11;
            }

            using var assetsStream = File.OpenRead(assetsPath);
            var assets = Activator.CreateInstance(assetMgrType, assetsStream);
            var ap = parserType.GetProperty("Assets");
            if (assets is null || ap is null || !ap.CanWrite)
            {
                Console.Error.WriteLine("Failed to construct AssetManager or set MgxcParser.Assets.");
                return 12;
            }
            ap.SetValue(parser, assets);
        }

        // 必须等待异步解析/转换完成；否则可能读到未填充的 Mgxc 或尚未写入的 c2s。
        FinishAsync(
            parserType.GetMethod("ActionAsync", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
                ?.Invoke(parser, new object?[] { default(CancellationToken) }));

        // 某些版本 ActionAsync 返回 Task<Chart>；这里通过属性取结果对象。
        var mgxcProp = parserType.GetProperty("Mgxc", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        var mgxc = mgxcProp?.GetValue(parser);
        if (mgxc is null)
        {
            Console.Error.WriteLine("Failed to obtain parsed mgxc object.");
            return 8;
        }

        var conv = Activator.CreateInstance(convType, diag, null);
        if (conv is null) return 9;
        convType.GetProperty("OutPath")?.SetValue(conv, outPath);
        convType.GetProperty("Mgxc")?.SetValue(conv, mgxc);
        FinishAsync(
            convType.GetMethod("ActionAsync", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
                ?.Invoke(conv, new object?[] { default(CancellationToken) }));

        if (!File.Exists(outPath))
        {
            Console.Error.WriteLine("Converter finished but output is missing.");
            return 10;
        }
        Console.WriteLine(outPath);
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        return 1;
    }
}

static void EnsurePenguinToolsCoreLoaded()
{
    if (AppDomain.CurrentDomain.GetAssemblies().Any(a => a.GetName().Name == "PenguinTools.Core"))
        return;

    var candidates = new List<string>();
    var env = Environment.GetEnvironmentVariable("CHUNI_PENGUIN_TOOLS_CORE_DLL");
    if (!string.IsNullOrWhiteSpace(env))
        candidates.Add(Path.GetFullPath(env.Trim()));

    var baseDir = AppContext.BaseDirectory;
    candidates.Add(Path.Combine(baseDir, "PenguinTools.Core.dll"));

    foreach (var p in candidates)
    {
        if (!File.Exists(p))
            continue;
        try
        {
            Assembly.LoadFrom(p);
            return;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Failed to load PenguinTools.Core from {p}: {ex.Message}");
        }
    }
}

return MainImpl(args);

