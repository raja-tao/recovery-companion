import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Stack, Typography } from "@mui/material";
import { useApi } from "../../api/client";
import { ErrorState, Loading, PageHeader, titleCase } from "../../components/common";

interface Item {
  id: string; title: string; summary: string; body: string; phase: string; reading_minutes: number; recommended: boolean;
  source: { title: string; version: number; authority: string } | null;
}

export default function Education() {
  const { data, error, loading } = useApi<Item[]>("/education");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} />;
  return (
    <Stack gap={2}>
      <PageHeader title="Recovery education" subtitle="Approved reading for your procedure. Recommended items match your current phase." />
      {data.map((e) => (
        <Accordion key={e.id} variant="outlined" disableGutters sx={{ borderRadius: 2, "&:before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreRounded />}>
            <Box>
              <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
                <Typography variant="subtitle1">{e.title}</Typography>
                {e.recommended && <Chip size="small" color="primary" label="Recommended now" />}
              </Stack>
              <Typography variant="body2" color="text.secondary">{e.summary} · {e.reading_minutes} min read</Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <Typography className="prewrap">{e.body}</Typography>
            {e.source && (
              <Typography variant="caption" color="text.secondary" display="block" mt={1.5}>
                Source: {e.source.title} (v{e.source.version}, {titleCase(e.source.authority)})
              </Typography>
            )}
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
}
