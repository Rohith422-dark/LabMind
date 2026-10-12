STEP_PROMPT = (
    "Extract the discrete procedural steps from this laboratory procedure, in order. "
    "For each step give: step_no (1-based, sequential), action (short imperative sentence), "
    "parameters (list of {name, value, unit}; name one of temperature, time, volume, cycles, speed, "
    "concentration, ph, mass, flow_rate, reagent, other; copy numbers exactly as written), "
    "is_critical (true only if the document marks it critical/must/warning), source_page (page number or null). "
    "Do not invent steps or numbers. If there are no discrete steps return an empty list."
)
