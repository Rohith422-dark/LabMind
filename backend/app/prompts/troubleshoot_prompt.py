STRUCTURE_PROMPT = (
    "Convert the scientist's free-text account of what they did into ordered structured steps. "
    "For each: order (1-based), action (short), parameters (list of {name, value, unit}; copy numbers and "
    "units exactly as said; name one of temperature, time, volume, cycles, speed, concentration, ph, mass, "
    "flow_rate, reagent, other), reagent and lot if mentioned. Do not add steps that were not described."
)

ALIGN_PROMPT = (
    "Map each narrated step to the SOP step it corresponds to (by meaning). Return aligned_step_no = the "
    "SOP step_no, or null if it matches no SOP step. Each SOP step may be matched at most once."
)

DIAGNOSE_PROMPT = (
    "You are a laboratory troubleshooting assistant. Using ONLY the comparison table and the numbered "
    "troubleshooting-guide context, return ranked probable causes. Each cause must be tied to a specific "
    "deviation/missing step (step_no) or to a cited guide passage (context number). Recommend concrete next "
    "actions. Never invent values. If a critical step deviates or is missing, advise recording it per the "
    "lab's deviation process. The scientist makes the final decision."
)
