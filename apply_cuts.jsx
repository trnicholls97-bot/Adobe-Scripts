/*
 * apply_cuts.jsx
 * ExtendScript for Adobe Premiere Pro
 *
 * Reads a JSON file produced by detect_silence.py and removes dead air
 * from the selected clip(s) on the active sequence timeline.
 *
 * HOW IT WORKS:
 *   Since ExtendScript cannot razor-cut clips, this script uses the
 *   "remove and re-insert" strategy:
 *     1. Reads the keep_regions from JSON
 *     2. For each selected audio/video clip pair, calculates the source
 *        in/out points for each keep region
 *     3. Removes the original clip
 *     4. Inserts sub-clips back-to-back with only the content regions
 *
 * USAGE:
 *   1. Run detect_silence.py on your source media to get a _cuts.json file
 *   2. In Premiere Pro, have your sequence open with the clip on the timeline
 *   3. Run this script via File > Scripts > Run Script File...
 *      or from a CEP panel via evalScript()
 *   4. It will prompt you to select the JSON file
 *   5. It will prompt you to confirm before modifying the timeline
 *
 * LIMITATIONS:
 *   - Operates on the FIRST clip of each audio track (track index 0)
 *     and the FIRST clip of each video track (track index 0).
 *     Modify targetAudioTrack / targetVideoTrack below for other tracks.
 *   - The clip must start at the beginning of the sequence (or adjust
 *     clipStartOffset below).
 *   - Applied effects on the original clip will NOT carry over to the
 *     new sub-clips. If you have effects, apply them after running this.
 */

// ============================================================
// CONFIGURATION — edit these to match your timeline layout
// ============================================================

var targetVideoTrack = 0; // V1 = index 0
var targetAudioTrack = 0; // A1 = index 0

// ============================================================
// HELPERS
// ============================================================

function readJsonFile(filePath) {
    var f = new File(filePath);
    if (!f.exists) {
        alert("JSON file not found:\n" + filePath);
        return null;
    }
    f.open("r");
    var content = f.read();
    f.close();

    // ExtendScript has no JSON.parse — use eval with safety wrapper
    try {
        var data = eval("(" + content + ")");
        return data;
    } catch (e) {
        alert("Failed to parse JSON:\n" + e.message);
        return null;
    }
}

function secondsToTicks(seconds) {
    // Premiere Pro internal tick rate: 254016000000 ticks per second
    // This is the standard PPro ticks-per-second constant
    var TICKS_PER_SECOND = 254016000000;
    return seconds * TICKS_PER_SECOND;
}

function ticksToSeconds(ticks) {
    var TICKS_PER_SECOND = 254016000000;
    return ticks / TICKS_PER_SECOND;
}

function createTimeFromSeconds(seconds) {
    var t = new Time();
    t.ticks = String(Math.round(secondsToTicks(seconds)));
    return t;
}

// ============================================================
// MAIN
// ============================================================

function main() {
    // Verify we have an active sequence
    var seq = app.project.activeSequence;
    if (!seq) {
        alert("No active sequence. Open a sequence first.");
        return;
    }

    // Prompt user to select JSON file
    var jsonFile = File.openDialog("Select the _cuts.json file", "JSON:*.json");
    if (!jsonFile) {
        return; // user cancelled
    }

    var data = readJsonFile(jsonFile.fsName);
    if (!data || !data.keep_regions || data.keep_regions.length === 0) {
        alert("No keep_regions found in JSON. Nothing to do.");
        return;
    }

    var regions = data.keep_regions;
    var summary = data.summary || {};

    // Show confirmation dialog
    var msg = "Dead Air Cutter\n\n";
    msg += "Source: " + (data.source_file || "unknown") + "\n";
    msg += "Content regions: " + regions.length + "\n";
    msg += "Content: " + (summary.total_content_sec || "?") + "s\n";
    msg += "Silence to remove: " + (summary.total_silence_sec || "?") + "s";
    msg += " (" + (summary.percent_removed || "?") + "%)\n\n";
    msg += "This will modify track V" + (targetVideoTrack + 1);
    msg += " and A" + (targetAudioTrack + 1) + ".\n";
    msg += "Proceed?";

    if (!confirm(msg)) {
        return;
    }

    // -----------------------------------------------------------
    // Get the clip on the target tracks
    // -----------------------------------------------------------
    var videoTrack = seq.videoTracks[targetVideoTrack];
    var audioTrack = seq.audioTracks[targetAudioTrack];

    if (!videoTrack && !audioTrack) {
        alert("Target tracks not found. Check targetVideoTrack / targetAudioTrack.");
        return;
    }

    // Find the first clip on each track
    var videoClip = null;
    var audioClip = null;
    var projectItem = null;

    if (videoTrack && videoTrack.clips.numItems > 0) {
        videoClip = videoTrack.clips[0];
        projectItem = videoClip.projectItem;
    }
    if (audioTrack && audioTrack.clips.numItems > 0) {
        audioClip = audioTrack.clips[0];
        if (!projectItem) {
            projectItem = audioClip.projectItem;
        }
    }

    if (!projectItem) {
        alert("No clips found on the target tracks.");
        return;
    }

    // Record the timeline start position of the original clip
    var clipStartSec = 0;
    if (videoClip) {
        clipStartSec = ticksToSeconds(parseFloat(videoClip.start.ticks));
    } else if (audioClip) {
        clipStartSec = ticksToSeconds(parseFloat(audioClip.start.ticks));
    }

    // Record source in-point offset (if clip was trimmed in source monitor)
    var sourceInSec = 0;
    if (videoClip) {
        sourceInSec = ticksToSeconds(parseFloat(videoClip.inPoint.ticks));
    } else if (audioClip) {
        sourceInSec = ticksToSeconds(parseFloat(audioClip.inPoint.ticks));
    }

    // -----------------------------------------------------------
    // Remove original clips from the tracks
    // -----------------------------------------------------------
    if (videoClip) {
        videoTrack.clips[0].remove(true, true);
        // params: (ripple, alignToVideo) — ripple=true to close gap
    }
    if (audioClip) {
        audioTrack.clips[0].remove(true, true);
    }

    // -----------------------------------------------------------
    // Insert sub-clips for each keep region
    // -----------------------------------------------------------
    var timelineInsertPoint = clipStartSec;

    for (var i = 0; i < regions.length; i++) {
        var region = regions[i];
        var regionStart = region.start_sec + sourceInSec;
        var regionEnd = region.end_sec + sourceInSec;

        // Set source in/out on the project item
        projectItem.setInPoint(regionStart, 4); // 4 = kMediaType_ANY
        projectItem.setOutPoint(regionEnd, 4);

        // Insert at current timeline position
        var insertTime = createTimeFromSeconds(timelineInsertPoint);

        // overwriteClip inserts the projectItem at the given time
        // using whatever in/out is set on the projectItem
        if (videoClip) {
            videoTrack.overwriteClip(projectItem, insertTime.ticks);
        }
        if (audioClip && !videoClip) {
            // Audio-only clip
            audioTrack.overwriteClip(projectItem, insertTime.ticks);
        }

        // Advance the insert point
        timelineInsertPoint += (regionEnd - regionStart);
    }

    // Clear source in/out to avoid confusion
    projectItem.clearInPoint(4);
    projectItem.clearOutPoint(4);

    alert(
        "Done! Inserted " + regions.length + " content regions.\n" +
        "Removed ~" + (summary.total_silence_sec || "?") + "s of dead air."
    );
}

main();
