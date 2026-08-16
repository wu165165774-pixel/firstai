export function promptRevisionSummary(...metadataItems) {
  const revisions = new Set();
  metadataItems.forEach((metadata) => {
    const provenance = metadata?.prompt_provenance;
    if (!Array.isArray(provenance)) return;
    provenance.forEach((item) => {
      const promptId = String(item?.prompt_id || "").trim();
      const revision = Number(item?.revision);
      if (promptId && Number.isInteger(revision) && revision > 0) {
        revisions.add(`${promptId}@r${revision}`);
      }
    });
  });
  return [...revisions].sort().join(" · ");
}
