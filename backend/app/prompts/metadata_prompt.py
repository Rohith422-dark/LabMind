METADATA_PROMPT = (
    "Extract document metadata from the first pages of a laboratory document. "
    "Return doc_code (the document's own identifier if printed, e.g. SOP-QC-012; otherwise empty), title, "
    "doc_type (one of SOP, protocol, troubleshooting_guide, manual), department, equipment (the main "
    "instrument or assay), revision (printed revision/version, or empty). Use empty strings when unknown. "
    "Never guess."
)
