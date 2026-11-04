import LocalHospitalRounded from "@mui/icons-material/LocalHospitalRounded";
import { Alert, Box, Button, Card, CardContent, Chip, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { Alert as AlertT } from "../../api/types";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader, SeverityChip, timeAgo } from "../../components/common";

interface Esc { id: string; alert: AlertT; to_role: string; reason: string; status: string; from: string; created_at: string; response_note: string | null }

export default function Escalations() {
  const { data, error, loading, reload } = useApi<Esc[]>("/escalations");
  const [notes, setNotes] = useState<Record<string, string>>({});
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;

  async function respond(e: Esc) {
    await api(`/escalations/${e.id}/respond`, { body: { response_note: notes[e.id], complete: true } });
    reload();
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Escalations for surgeon review" subtitle="Nurse-escalated cases. Your response is recorded in the patient timeline and audit trail." />
      {data.length === 0 && <EmptyState text="No open escalations." />}
      {data.map((e) => (
        <Card key={e.id}><CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={1}>
            <Stack direction="row" gap={1.5}>
              <LocalHospitalRounded color="warning" />
              <Box>
                <Stack direction="row" gap={1} alignItems="center"><Typography variant="h6">{e.alert.patient_name}</Typography><SeverityChip level={e.alert.severity} /></Stack>
                <Typography fontWeight={600}>{e.alert.trigger}</Typography>
                <Typography variant="body2" color="text.secondary">Escalated by {e.from} · {timeAgo(e.created_at)} · alert raised {fmtDateTime(e.alert.created_at)}</Typography>
              </Box>
            </Stack>
            <Chip label={e.status} />
          </Stack>
          <Alert severity="warning" sx={{ mt: 2 }}>Nurse: {e.reason}</Alert>
          <Stack direction={{ xs: "column", sm: "row" }} gap={1} mt={2}>
            <TextField fullWidth size="small" label="Your response / plan" value={notes[e.id] ?? ""} onChange={(ev) => setNotes({ ...notes, [e.id]: ev.target.value })} />
            <Button variant="contained" disabled={(notes[e.id] ?? "").length < 3} onClick={() => respond(e)}>Respond</Button>
            <Button component={RouterLink} to={`/care-team/patients/${e.alert.patient_id}?alert=${e.alert.id}`}>Open patient</Button>
          </Stack>
        </CardContent></Card>
      ))}
    </Stack>
  );
}
