using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using UnityEngine;

internal static class HexcellsHeadless
{
    private const BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

    private static object CreateComponent(Assembly game, string typeName, string objectName)
    {
        GameObject gameObject = new GameObject(objectName);
        Type type = game.GetType(typeName, true);
        return gameObject.AttachComponentObject(Activator.CreateInstance(type));
    }

    private static void Set(object target, string fieldName, object value)
    {
        FieldInfo field = target.GetType().GetField(fieldName, InstanceFlags);
        if (field == null) throw new MissingFieldException(target.GetType().FullName, fieldName);
        field.SetValue(target, value);
    }

    private static object Get(object target, string fieldName)
    {
        FieldInfo field = target.GetType().GetField(fieldName, InstanceFlags);
        if (field == null) throw new MissingFieldException(target.GetType().FullName, fieldName);
        return field.GetValue(target);
    }

    private static object Call(object target, string methodName, params object[] arguments)
    {
        MethodInfo method = target.GetType().GetMethod(methodName, InstanceFlags);
        if (method == null) throw new MissingMethodException(target.GetType().FullName, methodName);
        return method.Invoke(target, arguments);
    }

    private static GameObject CreateGroundPrefab(Assembly game, string name, string tag, object score)
    {
        GameObject prefab = new GameObject(name + " Prefab");
        prefab.tag = tag;
        GameObject number = new GameObject("Hex Number");
        number.AddComponent<TextMesh>();
        number.transform.parent = prefab.transform;
        return prefab;
    }

    private static GameObject CreateColumnPrefab(string name)
    {
        GameObject prefab = new GameObject(name + " Prefab");
        prefab.layer = 9;
        prefab.AddComponent<TextMesh>();
        return prefab;
    }

    private static GameObject CreateOrangePrefab(Assembly game, object score)
    {
        GameObject prefab = new GameObject("Orange Hex");
        object behaviour = prefab.AttachComponentObject(Activator.CreateInstance(game.GetType("HexBehaviour", true)));
        Set(behaviour, "score", score);
        prefab.AddComponent<MeshCollider>().enabled = true;
        return prefab;
    }

    private static int RawX(Transform transform)
    {
        return Mathf.RoundToInt(transform.position.x / 0.88f) + 15;
    }

    private static int RawY(Transform transform)
    {
        return Mathf.RoundToInt(transform.position.y / 0.5f) + 15;
    }

    private static string Clean(string value)
    {
        return (value ?? string.Empty).Replace("\t", " ").Replace("\r", " ").Replace("\n", " ");
    }

    private static string ChildText(Transform transform, string childName)
    {
        Transform child = transform.Find(childName);
        if (child == null) return string.Empty;
        TextMesh text = child.GetComponent<TextMesh>();
        return text == null ? string.Empty : text.text;
    }

    private static void Export(int seed)
    {
        Console.WriteLine("HEXINFINITE_EXPORT\t1");
        Console.WriteLine("SEED\t" + seed.ToString("D8", CultureInfo.InvariantCulture));
        foreach (Transform child in GameObject.Find("Hex Grid").transform)
        {
            Console.WriteLine(string.Format(
                CultureInfo.InvariantCulture,
                "CELL\t{0}\t{1}\t{2}\t{3}\t{4}\t{5}",
                RawX(child), RawY(child), Clean(child.name), Clean(child.tag), child.gameObject.layer,
                Clean(ChildText(child, "Hex Number"))
            ));
        }
        foreach (Transform child in GameObject.Find("Columns Parent").transform)
        {
            TextMesh text = child.GetComponent<TextMesh>();
            Console.WriteLine(string.Format(
                CultureInfo.InvariantCulture,
                "COLUMN\t{0}\t{1}\t{2}\t{3}\t{4}",
                RawX(child), RawY(child), Clean(child.name), Clean(child.tag),
                Clean(text == null ? string.Empty : text.text)
            ));
        }
    }

    private static void GenerateEasy(Assembly game, int seed)
    {
        GameObject.ResetScene();

        new GameObject("Hex Grid");
        new GameObject("Hex Grid Overlay");
        new GameObject("Columns Parent");

        object score = CreateComponent(game, "HexScoring", "Score Text");
        TextMesh remaining = ((Component)score).gameObject.AddComponent<TextMesh>();
        Set(score, "remainingText", remaining);
        Set(score, "isMarvinSolving", true);

        object editor = CreateComponent(game, "EditorFunctions", "Editor Functions");
        object solver = CreateComponent(game, "MarvinHexcellsSolver", "Solver");
        object generator = CreateComponent(game, "OldLevelGenerator", "Level Generator");

        GameObject black = CreateGroundPrefab(game, "Black Hex", "Untagged", score);
        GameObject blue = CreateGroundPrefab(game, "Blue Hex", "Blue", score);
        GameObject flower = CreateGroundPrefab(game, "Blue Hex (Flower)", "Blue", score);
        GameObject column = CreateColumnPrefab("Column Number");
        GameObject columnLeft = CreateColumnPrefab("Column Number Diagonal Left");
        GameObject columnRight = CreateColumnPrefab("Column Number Diagonal Right");
        GameObject orange = CreateOrangePrefab(game, score);
        GameObject blankOverlay = new GameObject("Blank Hex Overlay Parent");

        Set(editor, "orangeHex", orange);
        Set(editor, "blankHexOverlayParent", blankOverlay);

        Set(generator, "blackHex", black);
        Set(generator, "blueHex", blue);
        Set(generator, "blueFlowerHex", flower);
        Set(generator, "columnNumber", column);
        Set(generator, "columnNumberLeft", columnLeft);
        Set(generator, "columnNumberRight", columnRight);
        Set(generator, "editorFunctions", editor);
        Set(generator, "marvinHexcellsSolver", solver);
        Set(generator, "hexGridParent", GameObject.Find("Hex Grid").transform);
        Set(generator, "hexScoring", score);
        Set(generator, "seedValue", seed.ToString("D8", CultureInfo.InvariantCulture));
        Set(generator, "seedValueINT", seed);
        Set(solver, "levelGenerator", generator);
        Set(solver, "orangeHex", orange);

        Call(generator, "SetRandomVariables");
        float shape = (float)Call(generator, "ReturnRandom", 0f, 1f);
        if (shape <= 0.15f)
            Call(generator, "GenerateLevelDiamondShaping");
        else if (shape < 0.6f)
            Call(generator, "GenerateLevelHexShaping");
        else
            Call(generator, "GenerateLevel");

        Call(generator, "SetupLevel");
        int attempts = 0;
        while (!(bool)Call(solver, "Solve"))
        {
            Call(generator, "RevealAdditionalStartingHex");
            attempts++;
            Set(generator, "debugInfiniteLoopCheck", attempts);
            if (attempts >= 250)
                throw new InvalidOperationException("Marvin exceeded the original 250-attempt limit.");
        }
        Call(generator, "SetupLevelNoTagging");
        Export(seed);
    }

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 2 || !string.Equals(args[0], "easy", StringComparison.OrdinalIgnoreCase))
            {
                Console.Error.WriteLine("Usage: HexcellsHeadless easy <seed> < Assembly-CSharp path via HEXCELLS_ASSEMBLY>");
                return 2;
            }
            int seed;
            if (!int.TryParse(args[1], NumberStyles.None, CultureInfo.InvariantCulture, out seed) || seed < 0)
                throw new ArgumentOutOfRangeException("seed");
            string assemblyPath = Environment.GetEnvironmentVariable("HEXCELLS_ASSEMBLY");
            if (string.IsNullOrEmpty(assemblyPath) || !File.Exists(assemblyPath))
                throw new FileNotFoundException("Set HEXCELLS_ASSEMBLY to Assembly-CSharp.dll.orig.", assemblyPath);
            // Force the two headless dependency assemblies into the load context
            // before the original managed game assembly is opened.
            Type forceUnity = typeof(UnityEngine.GameObject);
            Type forceText = typeof(TMPro.TextMeshPro);
            Assembly game = Assembly.LoadFrom(Path.GetFullPath(assemblyPath));
            GenerateEasy(game, seed);
            return 0;
        }
        catch (TargetInvocationException exception)
        {
            Exception inner = exception.InnerException ?? exception;
            Console.Error.WriteLine(inner.GetType().FullName + ": " + inner.Message);
            Console.Error.WriteLine(inner.StackTrace);
            return 1;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.GetType().FullName + ": " + exception.Message);
            Console.Error.WriteLine(exception.StackTrace);
            return 1;
        }
    }
}
