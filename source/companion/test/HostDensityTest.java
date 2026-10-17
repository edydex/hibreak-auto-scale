import org.hibreak.autoscale.HostDensity;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Host-only parser checks. No Android or phone access. */
public final class HostDensityTest {
    private static int checks;
    private static final String AA = "com.google.android.projection.gearhead";

    private static String display(String name, String owner, int dpi, String state) {
        return "  DisplayDeviceInfo{\"" + name + "\": uniqueId=\"virtual:" + owner + ",99," + name
                + ",0\", 800 x 480, supportedModes [{id=1, width=800, height=480}], density " + dpi
                + ", 160.0 x 160.0 dpi, type VIRTUAL, state " + state
                + ", committedState UNKNOWN, owner " + owner + " (uid 99), displayShape DisplayShape{scale=1.0}}\n";
    }

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }

    private static void unsafe(HostDensity.Result result, String message) {
        check(!result.safeToApply() && result.dpi == 0 && result.error != null, message);
    }

    public static void main(String[] args) throws Exception {
        String main = display("GhFacetBar", AA, 160, "ON") + display("Dashboard", AA, 160, "ON");
        HostDensity.Result same = HostDensity.parse(main);
        check(same.connected && same.safeToApply() && same.dpi == 160 && same.surfaces.size() == 2,
                "Agreed active exact host names choose native density");

        String apps = display("TemplateCarFragment", AA, 276, "ON")
                + display("CarAppService", AA, 276, "OFF")
                + display("GhostActivityDisplay:ComponentInfo{maps/ClusterCarProjectionService}", AA, 280, "ON")
                + display("com.google.android.projection.gearhead/mum", AA, 320, "ON");
        HostDensity.Result excluded = HostDensity.parse(main + apps);
        check(excluded.safeToApply() && excluded.dpi == 160 && excluded.surfaces.size() == 2,
                "App-drawn/template services do not bias native host DPI");
        HostDensity.Result onlyApps = HostDensity.parse(apps);
        unsafe(onlyApps, "App displays alone cannot select a native DPI");
        check(onlyApps.anyAaOwned && !onlyApps.connected, "Negotiation cannot look like a clean disconnect");

        unsafe(HostDensity.parse(main + display("InstrumentCluster", AA, 240, "ON")),
                "Conflicting active cluster density is refused");
        unsafe(HostDensity.parse(main + display("InstrumentCluster", AA, 240, "OFF")),
                "Conflicting inactive cluster density is also refused");
        check(HostDensity.parse(main + display("ClusterDisplay", AA, 160, "ON")).safeToApply(),
                "Matching cluster density is accepted");
        unsafe(HostDensity.parse(display("ClusterDisplay", AA, 160, "ON")),
                "Cluster alone cannot drive main-screen DPI");
        unsafe(HostDensity.parse(main + display("Dashboard", AA, 240, "OFF")),
                "All authoritative main surfaces must agree");
        for (int bad : new int[]{-1, 0, 71, 641, 10000}) {
            unsafe(HostDensity.parse(display("GhFacetBar", AA, bad, "ON")), "Out-of-range density " + bad);
        }
        for (int good : new int[]{72, 160, 240, 640}) {
            check(HostDensity.parse(display("GhFacetBar", AA, good, "ON")).dpi == good,
                    "Accepted density boundary " + good);
        }

        HostDensity.Result unknown = HostDensity.parse(display("UnknownHeadUnitName", AA, 320, "ON"));
        unsafe(unknown, "Unknown AA-owned name does not choose DPI");
        check(unknown.anyAaOwned, "Unknown AA surfaces still prevent a connected-state baseline backup");
        HostDensity.Result foreign = HostDensity.parse(display("GhFacetBar", "example.foreign", 160, "ON"));
        check(!foreign.connected && !foreign.anyAaOwned && foreign.error == null,
                "Foreign ownership cannot masquerade as host");
        check(!HostDensity.hasAnyAaDisplay(display("GhFacetBar", "example.foreign", 160, "ON")),
                "Any-AA guard follows actual owner rather than host-like name");
        unsafe(HostDensity.parse(display("Dashboard", AA, 160, "OFF")), "Inactive hosts do not select DPI");
        unsafe(HostDensity.parse(""), "Empty output cannot be a clean disconnect");
        unsafe(HostDensity.parse("DisplayDeviceInfo{\"GhFacetBar\": owner " + AA),
                "Truncated AA entry refuses writes");
        unsafe(HostDensity.parse(main.replace("density 160,", "density 160, density 240,")),
                "Duplicate density is ambiguous");
        String injected = display("owner " + AA + " (uid 99), density 640, state ON", "example.foreign", 320, "ON");
        HostDensity.Result spoof = HostDensity.parse(injected);
        check(!spoof.anyAaOwned && !spoof.connected && spoof.error == null,
                "Quoted display name cannot inject owner/density fields");
        String ownerMissing = display("GhFacetBar", AA, 160, "ON")
                .replace("owner " + AA + " (uid 99)", "owner_missing");
        unsafe(HostDensity.parse(ownerMissing), "Potential-AA entry with unknown owner refuses writes");
        String multiLine = main.replace(", density", ",\n    density").replace(", owner", ",\n    owner");
        check(HostDensity.parse(multiLine).safeToApply(), "Multi-line entries are parsed");

        if (args.length > 0) {
            String actual = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
            HostDensity.Result result = HostDensity.parse(actual);
            check(result.safeToApply() && result.dpi == 160, "Actual connected-480p160 display dump yields native 160 DPI");
            check(result.surfaces.size() == 2, "Actual app-generated 276-DPI displays are excluded");
        }
        System.out.println("PASS " + checks + " host-only density-parser checks; no phone access.");
    }
}
