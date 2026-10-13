STRUCTURE_PROMPT = (
    "Convert the scientist's free-text account of what they did into ordered structured steps. "
    "Use the SAME granularity as the SOP steps shown for reference: combine micro-actions that belong to one SOP "
    "step (for example rinsing, drying, placing the probe and clicking read) into ONE narrated step, and put every "
    "number the scientist stated for that step (such as pH 6.00) into its parameters with the unit. "
    "For each: order (1-based), action (short), parameters (list of {name, value, unit}; copy numbers and "
    "units exactly as said; name one of temperature, time, volume, cycles, speed, concentration, ph, mass, "
    "flow_rate, reagent, other), reagent and lot if mentioned. Do not add steps that were not described."
)

ALIGN_PROMPT = (
    "Map each narrated step to the SOP step it corresponds to by PURPOSE and POSITION in the sequence. A narrated "
    "step that does the same job as an SOP step but with a different value (for example a different buffer, time or "
    "temperature) STILL maps to that SOP step: the value difference is checked later by rules. Return "
    "aligned_step_no = the SOP step_no, or null only if the step does something no SOP step covers. Each SOP "
    "step may be matched at most once and the order of matches should follow the SOP order."
)

DIAGNOSE_PROMPT = (
    "You are a laboratory troubleshooting assistant. Using ONLY the comparison table and the numbered "
    "troubleshooting-guide context, return ranked probable causes. Each cause must be tied to a specific "
    "deviation/missing step (step_no) or to a cited guide passage (context number). Recommend concrete next "
    "actions. Never invent values. If a critical step deviates or is missing, advise recording it per the "
    "lab's deviation process. The scientist makes the final decision."
)
