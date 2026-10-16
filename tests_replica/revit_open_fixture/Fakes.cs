// Fixture-only API doubles: no Autodesk runtime, model, share, or installation.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using RevitMCPCore;

namespace Autodesk.Revit.DB
{
    public class ElementId { }
    public class View { public string Name { get; set; } = "Default"; public bool IsTemplate; public ElementId Id = new ElementId(); }
    public class Document
    {
        public string Title = "Fixture"; public string PathName = ""; public bool IsWorkshared;
        public bool IsModifiable; public List<View> Views = new List<View> {
            new View { Name = "Plan" }, new View { Name = "Template", IsTemplate = true },
            new View { Name = "Duplicate" }, new View { Name = "Duplicate" } };
        public void ExportImage(ImageExportOptions options) { }
    }
    public class ModelPath : IDisposable { public string Path; public void Dispose() { } }
    public static class ModelPathUtils
    {
        public static string LastPath;
        public static ModelPath ConvertUserVisiblePathToModelPath(string path)
        { LastPath = path; return new ModelPath { Path = path }; }
    }
    public class OpenOptions : IDisposable { public void Dispose() { } }
    public class FilteredElementCollector : IEnumerable<View>
    {
        private Document doc;
        public FilteredElementCollector(Document d) { doc = d; }
        public FilteredElementCollector OfClass(Type type) => this;
        public IEnumerator<View> GetEnumerator() => doc.Views.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
    public enum TransactionStatus { Started, Committed, RolledBack, Pending }
    public class Transaction : IDisposable
    {
        public static int Starts, Commits, Rollbacks;
        public static bool RefuseStart;
        public static TransactionStatus StartResult = TransactionStatus.Started, CommitResult = TransactionStatus.Committed, RollbackResult = TransactionStatus.RolledBack;
        public static bool ThrowOnRollback;
        private Document doc; private bool started;
        public Transaction(Document d, string name) { doc = d ?? throw new Exception("null transaction document"); }
        public TransactionStatus Start() { if (RefuseStart) throw new Exception("fixture start refused"); if (StartResult != TransactionStatus.Started) return StartResult; Starts++; started = doc.IsModifiable = true; return StartResult; }
        public bool HasStarted() => started;
        public TransactionStatus GetStatus() => started ? TransactionStatus.Started : TransactionStatus.Committed;
        public TransactionStatus Commit() { Commits++; started = doc.IsModifiable = false; return CommitResult; }
        public TransactionStatus RollBack() { Rollbacks++; if (ThrowOnRollback) { started = false; throw new Exception("fixture rollback refused"); } started = doc.IsModifiable = false; return RollbackResult; }
        public void Dispose() { if (started) RollBack(); }
    }
    public enum ExportRange { SetOfViews }
    public enum ImageFileType { PNG }
    public enum ImageResolution { DPI_300 }
    public enum ZoomFitType { FitToPage }
    public class ImageExportOptions
    {
        public ExportRange ExportRange; public ImageFileType HLRandWFViewsFileType;
        public ImageResolution ImageResolution; public int PixelSize; public string FilePath; public ZoomFitType ZoomType;
        public void SetViewsAndSheets(List<ElementId> ids) { }
    }
}
namespace Autodesk.Revit.UI
{
    using Autodesk.Revit.DB;
    public interface IExternalEventHandler { void Execute(UIApplication app); string GetName(); }
    public class ExternalEvent { public void Raise() { } }
    public class ApplicationInfo { public string VersionName = "fixture"; public string Username = "fixture"; }
    public class UIDocument
    {
        public Document Document; private View view = new View();
        public View ActiveView { get => view; set { if (value.Name == "Invalid") throw new Exception("not activatable"); view = value; } }
    }
    public class UIApplication
    {
        public static bool InExternalEvent;
        public UIDocument ActiveUIDocument; public ApplicationInfo Application = new ApplicationInfo();
        public int Opens; public bool FailOpen;
        public UIDocument OpenAndActivateDocument(ModelPath path, OpenOptions options, bool detachAndPrompt)
        {
            if (!InExternalEvent) throw new Exception("not in ExternalEvent");
            if (ActiveUIDocument?.Document.IsModifiable == true) throw new Exception("modifiable active document");
            if (FailOpen) throw new Exception("fixture open refused");
            if (detachAndPrompt) throw new Exception("user prompt forbidden");
            Opens++; ActiveUIDocument = new UIDocument { Document = new Document { PathName = path.Path } };
            ActiveUIDocument.Document.Views.Add(new View { Name = "Invalid" });
            return ActiveUIDocument;
        }
    }
}
namespace ArchHub.Shared
{
    public class ScriptResult { public string Status, Error; public object Result; public bool CacheHit; }
    public static class ScriptCompiler
    {
        public static int Calls;
        public static string ProbeCsc() => "fixture";
        public static (string, string) ProbeCscDetailed() => ("fixture", "ok");
        public static ScriptResult CompileAndRun(string userCode, object ctx, string scriptContextFullName,
            IEnumerable<string> references, IEnumerable<string> usings, string langVersion)
        {
            Calls++; var context = (ScriptContext)ctx;
            if (userCode == "throw") throw new Exception("fixture compiler crash");
            if (userCode == "fail") return new ScriptResult { Status = "runtime_error", Error = "fixture failure" };
            if (userCode == "open")
                context.UIApp.OpenAndActivateDocument(new Autodesk.Revit.DB.ModelPath { Path = "fixture" }, new Autodesk.Revit.DB.OpenOptions(), false);
            context.result = new { doc_null = context.Doc == null, uidoc_null = context.UIDoc == null,
                modifiable = context.Doc?.IsModifiable == true };
            return new ScriptResult { Status = "ok" };
        }
    }
}
