using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

namespace UnityEngine
{
    public class Object
    {
        internal bool destroyed;
        private string objectName = string.Empty;

        public virtual string name
        {
            get { return objectName; }
            set { objectName = value ?? string.Empty; }
        }

        public static bool op_Equality(Object left, Object right)
        {
            bool leftNull = ReferenceEquals(left, null) || (!ReferenceEquals(left, null) && left.destroyed);
            bool rightNull = ReferenceEquals(right, null) || (!ReferenceEquals(right, null) && right.destroyed);
            if (leftNull || rightNull)
                return leftNull == rightNull;
            return ReferenceEquals(left, right);
        }

        public static bool op_Inequality(Object left, Object right)
        {
            return !op_Equality(left, right);
        }

        public override bool Equals(object value)
        {
            return op_Equality(this, value as Object);
        }

        public override int GetHashCode()
        {
            return base.GetHashCode();
        }

        public static T Instantiate<T>(T original) where T : Object
        {
            return Instantiate(original, Vector3.zero, Quaternion.identity, null);
        }

        public static T Instantiate<T>(T original, Vector3 position, Quaternion rotation) where T : Object
        {
            return Instantiate(original, position, rotation, null);
        }

        public static T Instantiate<T>(T original, Vector3 position, Quaternion rotation, Transform parent) where T : Object
        {
            GameObject source = original as GameObject;
            if (source == null)
                throw new NotSupportedException("The headless runtime only clones GameObject instances.");
            GameObject clone = source.DeepClone();
            clone.transform.position = position;
            clone.transform.rotation = rotation;
            if (parent != null)
                clone.transform.parent = parent;
            return (T)(Object)clone;
        }

        public static void DestroyImmediate(Object value)
        {
            Destroy(value);
        }

        public static void Destroy(Object value)
        {
            if (ReferenceEquals(value, null) || value.destroyed)
                return;
            GameObject gameObject = value as GameObject;
            Component component = value as Component;
            if (gameObject == null && component != null)
                gameObject = component.gameObject;
            if (gameObject != null)
                gameObject.DestroyNow();
            else
                value.destroyed = true;
        }
    }

    public class Component : Object
    {
        internal GameObject owner;

        public GameObject gameObject { get { return owner; } }
        public Transform transform { get { return owner == null ? null : owner.transform; } }

        public override string name
        {
            get { return owner == null ? base.name : owner.name; }
            set { if (owner == null) base.name = value; else owner.name = value; }
        }

        public string tag
        {
            get { return owner.tag; }
            set { owner.tag = value; }
        }

        public T GetComponent<T>() where T : class
        {
            return owner.GetComponent<T>();
        }

        public Component GetComponent(string typeName)
        {
            return owner.GetComponent(typeName);
        }
    }

    public class Behaviour : Component { }

    public class MonoBehaviour : Behaviour
    {
        public Coroutine StartCoroutine(string methodName) { return null; }
        public Coroutine StartCoroutine(IEnumerator routine) { return null; }
        public static void print(object value) { Debug.Log(value); }
    }

    public class Coroutine : Object { }

    public class GameObject : Object
    {
        private static readonly List<GameObject> Registry = new List<GameObject>();
        private readonly List<Component> components = new List<Component>();

        private int layerValue;
        private string tagValue = "Untagged";

        public int layer
        {
            get { return layerValue; }
            set { layerValue = value; }
        }

        public string tag
        {
            get { return tagValue; }
            set { tagValue = value ?? "Untagged"; }
        }
        public GameObject gameObject { get { return this; } }
        public Transform transform { get; private set; }

        public GameObject() : this("GameObject") { }

        public GameObject(string objectName)
        {
            name = objectName;
            transform = new Transform();
            AttachComponent(transform);
            Registry.Add(this);
        }

        public static void ResetScene()
        {
            Registry.Clear();
        }

        public static GameObject Find(string objectName)
        {
            for (int index = Registry.Count - 1; index >= 0; index--)
            {
                GameObject candidate = Registry[index];
                if (!candidate.destroyed && candidate.name == objectName)
                    return candidate;
            }
            return null;
        }

        public Component AttachComponent(Component component)
        {
            component.owner = this;
            components.Add(component);
            return component;
        }

        public object AttachComponentObject(object value)
        {
            Component component = value as Component;
            if (component == null)
                throw new ArgumentException("Component must derive from UnityEngine.Component.");
            return AttachComponent(component);
        }

        public T AddComponent<T>() where T : Component, new()
        {
            return (T)AttachComponent(new T());
        }

        public Component AddComponent(Type type)
        {
            return AttachComponent((Component)Activator.CreateInstance(type));
        }

        public T GetComponent<T>() where T : class
        {
            foreach (Component component in components)
            {
                T match = component as T;
                if (match != null)
                    return match;
            }
            return null;
        }

        public Component GetComponent(string typeName)
        {
            foreach (Component component in components)
            {
                if (component.GetType().Name == typeName || component.GetType().FullName == typeName)
                    return component;
            }
            return null;
        }

        internal GameObject DeepClone()
        {
            return DeepClone(true);
        }

        private GameObject DeepClone(bool appendCloneSuffix)
        {
            GameObject clone = new GameObject(appendCloneSuffix ? name + "(Clone)" : name);
            clone.layer = layer;
            clone.tag = tag;
            clone.transform.position = transform.position;
            clone.transform.rotation = transform.rotation;
            foreach (Component source in components)
            {
                if (source is Transform)
                    continue;
                Component destination = (Component)Activator.CreateInstance(source.GetType());
                CopyFields(source, destination);
                clone.AttachComponent(destination);
            }
            foreach (Transform child in transform)
            {
                GameObject childClone = child.gameObject.DeepClone(false);
                childClone.transform.parent = clone.transform;
            }
            return clone;
        }

        private static void CopyFields(object source, object destination)
        {
            Type type = source.GetType();
            while (type != null && type != typeof(Component) && type != typeof(Object))
            {
                foreach (FieldInfo field in type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
                {
                    if (!field.IsInitOnly)
                        field.SetValue(destination, field.GetValue(source));
                }
                type = type.BaseType;
            }
        }

        internal void DestroyNow()
        {
            if (destroyed)
                return;
            destroyed = true;
            transform.DetachFromParent();
            foreach (Transform child in new List<Transform>(transform.Children))
                child.gameObject.DestroyNow();
            foreach (Component component in components)
                component.destroyed = true;
        }
    }

    public class Transform : Component, IEnumerable
    {
        private Transform parentValue;
        internal readonly List<Transform> Children = new List<Transform>();

        private Vector3 positionValue;
        private Quaternion rotationValue = Quaternion.identity;

        public Vector3 position
        {
            get { return positionValue; }
            set { positionValue = value; }
        }

        public Quaternion rotation
        {
            get { return rotationValue; }
            set { rotationValue = value; }
        }

        public Transform parent
        {
            get { return parentValue; }
            set
            {
                if (ReferenceEquals(parentValue, value))
                    return;
                DetachFromParent();
                parentValue = value;
                if (parentValue != null)
                    parentValue.Children.Add(this);
            }
        }

        internal void DetachFromParent()
        {
            if (parentValue != null)
                parentValue.Children.Remove(this);
            parentValue = null;
        }

        public int childCount { get { return Children.Count; } }
        public Transform GetChild(int index) { return Children[index]; }

        public Transform Find(string childName)
        {
            foreach (Transform child in Children)
            {
                if (!child.destroyed && child.name == childName)
                    return child;
            }
            return null;
        }

        public IEnumerator GetEnumerator()
        {
            return new LiveEnumerator(this);
        }

        private sealed class LiveEnumerator : IEnumerator
        {
            private readonly Transform owner;
            private int index = -1;
            public LiveEnumerator(Transform owner) { this.owner = owner; }
            public object Current { get { return owner.Children[index]; } }
            public bool MoveNext() { index++; return index < owner.Children.Count; }
            public void Reset() { index = -1; }
        }
    }

    public struct Vector3
    {
        public float x;
        public float y;
        public float z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
        public static Vector3 zero { get { return new Vector3(0f, 0f, 0f); } }
        public override string ToString() { return string.Format("({0}, {1}, {2})", x, y, z); }
    }

    public struct Quaternion
    {
        public float x;
        public float y;
        public float z;
        public float w;
        public static Quaternion identity { get { return new Quaternion { w = 1f }; } }
    }

    public static class Mathf
    {
        public static int RoundToInt(float value) { return (int)Math.Round(value, MidpointRounding.ToEven); }
        public static int FloorToInt(float value) { return (int)Math.Floor(value); }
        public static int CeilToInt(float value) { return (int)Math.Ceiling(value); }
        public static int Abs(int value) { return Math.Abs(value); }
        public static float Abs(float value) { return Math.Abs(value); }
        public static int Min(int left, int right) { return Math.Min(left, right); }
        public static float Min(float left, float right) { return Math.Min(left, right); }
        public static float Lerp(float minimum, float maximum, float amount)
        {
            if (amount < 0f) amount = 0f;
            if (amount > 1f) amount = 1f;
            return minimum + (maximum - minimum) * amount;
        }
    }

    public static class Random
    {
        private const uint Multiplier = 1812433253u;
        private static readonly uint[] Words = new uint[4];

        public struct State
        {
            internal int s0;
            internal int s1;
            internal int s2;
            internal int s3;
        }

        public static int seed { set { InitState(value); } }
        public static State state
        {
            get { return new State { s0 = (int)Words[0], s1 = (int)Words[1], s2 = (int)Words[2], s3 = (int)Words[3] }; }
            set { Words[0] = (uint)value.s0; Words[1] = (uint)value.s1; Words[2] = (uint)value.s2; Words[3] = (uint)value.s3; }
        }

        public static void InitState(int seedValue)
        {
            uint word = unchecked((uint)seedValue);
            Words[0] = word;
            for (int index = 1; index < 4; index++)
            {
                word = unchecked(Multiplier * word + 1u);
                Words[index] = word;
            }
        }

        private static uint Next()
        {
            uint temporary = Words[0] ^ (Words[0] << 11);
            uint result = Words[3] ^ (Words[3] >> 19) ^ temporary ^ (temporary >> 8);
            Words[0] = Words[1]; Words[1] = Words[2]; Words[2] = Words[3]; Words[3] = result;
            return result;
        }

        public static float value { get { return (float)(Next() & 0x7fffffu) / 8388607f; } }

        public static int Range(int minimum, int maximum)
        {
            if (maximum <= minimum) return minimum;
            return minimum + (int)(Next() % (uint)(maximum - minimum));
        }

        public static float Range(float minimum, float maximum)
        {
            return minimum + (1f - value) * (maximum - minimum);
        }
    }

    public class TextMesh : Component
    {
        private string textValue = string.Empty;
        public string text
        {
            get { return textValue; }
            set { textValue = value ?? string.Empty; }
        }
    }
    public class Collider : Component
    {
        private bool enabledValue = true;
        public bool enabled
        {
            get { return enabledValue; }
            set { enabledValue = value; }
        }
    }
    public class MeshCollider : Collider { }
    public class Renderer : Component { public Material material; public Material sharedMaterial; }
    public class Material : Object { public int renderQueue; }
    public class ParticleSystem : Component { }
    public class WaitForSeconds { public WaitForSeconds(float seconds) { } }
    public static class Time { public static float deltaTime { get { return 0f; } } }
    public static class Debug
    {
        public static void Log(object value) { }
        public static void LogWarning(object value) { Console.Error.WriteLine(value); }
    }
    public static class Input
    {
        public static bool GetMouseButtonDown(int button) { return false; }
    }
    public static class Application
    {
        public static void LoadLevel(int level) { }
        public static void Quit() { }
    }
    public class ExecuteInEditMode : Attribute { }
    public class SerializeField : Attribute { }
}
