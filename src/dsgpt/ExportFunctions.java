// Reviewed headless export; function failures remain explicit in the index.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import java.nio.file.*;
import java.io.*;
public class ExportFunctions extends GhidraScript {
    public void run() throws Exception {
        Path out = Paths.get(getScriptArgs()[0]);
        Files.createDirectories(out);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int count = 0;
        try (PrintWriter index = new PrintWriter(Files.newBufferedWriter(out.resolve("functions.tsv")))) {
            index.println("address\tname\tstatus\tfile");
            for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
                if (monitor.isCancelled() || count >= 5000) { index.println("INCOMPLETE: export stopped at 5000 functions or cancellation"); break; }
                if (function.isExternal()) continue;
                String address = function.getEntryPoint().toString().replace(':','_');
                String filename = address + ".c";
                DecompileResults result = decompiler.decompileFunction(function, 15, monitor);
                boolean ok = result.decompileCompleted() && result.getDecompiledFunction() != null;
                if (ok) Files.writeString(out.resolve(filename), result.getDecompiledFunction().getC());
                index.println(address + "\t" + function.getName().replace('\t',' ') + "\t" + (ok ? "decompiled" : "FAILED: " + result.getErrorMessage().replace('\n',' ')) + "\t" + (ok ? filename : ""));
                count++;
            }
        } finally { decompiler.dispose(); }
    }
}
