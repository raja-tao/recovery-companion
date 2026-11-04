import InfoOutlined from "@mui/icons-material/InfoOutlined";
import MedicationRounded from "@mui/icons-material/MedicationRounded";
import {
  Alert, Box, Button, ButtonGroup, Card, CardContent, Chip, Divider, Grid, Stack, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import type { MedSlot } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDate, fmtDateTime, Loading, PageHeader, Section } from "../../components/common";
import { MedStatus } from "./PatientHome";

interface Med {
  id: string; name: string; dose_text: string; indication: string; frequency: string; schedule_times: string[];
  as_needed: boolean; start_date: string; end_date: string | null; instructions: string; missed_dose_guidance: string | null;
  guidance_approved_by: string | null; prescriber: string | null;
}
interface MedsResponse {
  medications: Med[]; today: MedSlot[]; notice: string;
  recent_events: { id: string; name: string; scheduled_for: string; status: string }[];
  adherence: { rate: number | null; counts: Record<string, number> };
}

export default function Medications() {
  const { user } = useAuth();
  const pid = user!.patient_id;
  const { data, error, loading, reload } = useApi<MedsResponse>(`/patients/${pid}/medications`);
  const [msg, setMsg] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} onRetry={reload} />;

  async function record(slot: MedSlot, status: string) {
    const r = await api<{ alert_id: string | null }>(`/patients/${pid}/medications/${slot.medication_id}/events`, {
      body: { status, scheduled_for: slot.scheduled_for ?? undefined },
    });
    setMsg(r.alert_id ? "Recorded. Because several doses were missed, your nurse will check in with you."
      : `Recorded ${slot.name} as ${status.toLowerCase()}.`);
    reload();
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Medications" subtitle="Record each dose so your care team can support you."
        action={data.adherence.rate != null && <Chip color="primary" variant="outlined" label={`Recent doses taken: ${Math.round(data.adherence.rate * 100)}%`} />} />
      <Alert severity="info" icon={<InfoOutlined />}>{data.notice}</Alert>
      {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}

      <Section title="Today's schedule" icon={<MedicationRounded color="primary" />} id="today">
        <Stack divider={<Divider flexItem />} gap={1.5}>
          {data.today.map((s, i) => (
            <Stack key={i} direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} gap={1}>
              <Box>
                <Typography fontWeight={600}>{s.time} · {s.name} <Typography component="span" color="text.secondary">({s.dose_text})</Typography></Typography>
                <Typography variant="body2" color="text.secondary">{s.instructions}</Typography>
              </Box>
              <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
                <MedStatus status={s.status} />
                <ButtonGroup size="small" variant="outlined" aria-label={`Record ${s.name} ${s.time}`}>
                  <Button onClick={() => record(s, "TAKEN")}>Taken</Button>
                  {!s.as_needed && <Button onClick={() => record(s, "MISSED")}>Missed</Button>}
                  {!s.as_needed && <Button onClick={() => record(s, "SKIPPED")}>Skipped</Button>}
                  {!s.as_needed && <Button onClick={() => record(s, "UNKNOWN")}>Not sure</Button>}
                </ButtonGroup>
              </Stack>
            </Stack>
          ))}
        </Stack>
      </Section>

      <Typography variant="h6" component="h2">Your medication list</Typography>
      <Grid container spacing={2}>
        {data.medications.map((m) => (
          <Grid item xs={12} md={6} key={m.id}>
            <Card sx={{ height: "100%" }}><CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
                <Box>
                  <Typography variant="subtitle1">{m.name} · {m.dose_text}</Typography>
                  <Typography color="text.secondary">{m.frequency} · for {m.indication}</Typography>
                </Box>
                {m.as_needed && <Chip size="small" label="As needed" />}
              </Stack>
              <Typography variant="body2" mt={1}>{m.instructions}</Typography>
              <Box mt={1.5} p={1.5} sx={{ bgcolor: "#f9fafb", borderRadius: 2 }}>
                <Typography variant="caption" fontWeight={700} color="text.secondary">IF YOU MISS A DOSE</Typography>
                <Typography variant="body2">
                  {m.missed_dose_guidance ?? "No approved missed-dose instructions. Contact your care team — don't take extra. Your doctor decides any change."}
                </Typography>
                {m.guidance_approved_by && <Typography variant="caption" color="text.secondary">Approved by {m.guidance_approved_by}</Typography>}
              </Box>
              <Typography variant="caption" color="text.secondary" display="block" mt={1}>
                {fmtDate(m.start_date)} – {m.end_date ? fmtDate(m.end_date) : "ongoing"} · Prescriber {m.prescriber}
              </Typography>
            </CardContent></Card>
          </Grid>
        ))}
      </Grid>

      <Section title="Recent doses" id="recent">
        <Stack gap={0.5}>
          {data.recent_events.slice(0, 12).map((e) => (
            <Stack key={e.id} direction="row" justifyContent="space-between">
              <Typography variant="body2">{fmtDateTime(e.scheduled_for)} · {e.name}</Typography>
              <MedStatus status={e.status} />
            </Stack>
          ))}
        </Stack>
      </Section>
    </Stack>
  );
}
