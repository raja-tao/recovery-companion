import AssignmentRounded from "@mui/icons-material/AssignmentRounded";
import CheckCircleRounded from "@mui/icons-material/CheckCircleRounded";
import {
  Alert, Box, Button, Card, CardContent, Chip, FormControlLabel, FormLabel, Radio, RadioGroup, Stack, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import type { SurveyState } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorState, fmtDate, Loading, PageHeader } from "../../components/common";

type Definition = { instrument: string; title: string; intro: string; options: string[]; items: { id: string; domain: string; text: string }[] };

const STATE_CHIP: Record<SurveyState["state"], { label: string; color: "default" | "success" | "primary" | "warning" }> = {
  DUE: { label: "Ready now", color: "primary" }, COMPLETED: { label: "Done", color: "success" },
  UPCOMING: { label: "Later", color: "default" }, MISSED: { label: "Window closed", color: "warning" },
};

export default function Surveys() {
  const { user } = useAuth();
  const pid = user!.patient_id;
  const { data, error, loading, reload } = useApi<SurveyState[]>(`/patients/${pid}/surveys`);
  const [open, setOpen] = useState<SurveyState | null>(null);
  const [done, setDone] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} onRetry={reload} />;

  return (
    <Stack gap={2.5}>
      <PageHeader title="Recovery surveys" subtitle="Short questionnaires that show your surgeon how your joint is improving. Your answers are added to your hospital record." />
      {done && <Alert severity="success" onClose={() => setDone(null)}>{done}</Alert>}
      {data.length === 0 && <EmptyState text="There are no surveys in your recovery program." />}
      {open ? <SurveyForm survey={open} patientId={pid!} onCancel={() => setOpen(null)} onDone={(m) => { setOpen(null); setDone(m); reload(); }} /> :
        data.map((s) => (
          <Card key={s.timepoint}><CardContent>
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={1.5} alignItems={{ sm: "center" }}>
              <Stack direction="row" gap={1.5} alignItems="center">
                {s.state === "COMPLETED" ? <CheckCircleRounded color="success" /> : <AssignmentRounded color="primary" />}
                <Box>
                  <Typography fontWeight={600}>{s.title}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {s.label} · recovery days {s.window[0]}–{s.window[1]}
                    {s.completed_at && ` · completed ${fmtDate(s.completed_at)}`}
                  </Typography>
                </Box>
              </Stack>
              <Stack direction="row" gap={1} alignItems="center">
                <Chip size="small" label={STATE_CHIP[s.state].label} color={STATE_CHIP[s.state].color} variant={s.state === "UPCOMING" ? "outlined" : "filled"} />
                {s.state === "DUE" && <Button variant="contained" onClick={() => setOpen(s)}>Start (2 min)</Button>}
              </Stack>
            </Stack>
          </CardContent></Card>
        ))}
    </Stack>
  );
}

function SurveyForm({ survey, patientId, onCancel, onDone }: { survey: SurveyState; patientId: string; onCancel: () => void; onDone: (m: string) => void }) {
  const { data } = useApi<Definition>(`/surveys/${survey.instrument}`);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return <Loading />;
  const complete = data.items.every((i) => answers[i.id] !== undefined);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>(`/patients/${patientId}/surveys/${survey.instrument}/${survey.timepoint}`, { body: { answers } });
      onDone(r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card><CardContent>
      <Typography variant="h6" component="h2">{data.title}</Typography>
      <Typography color="text.secondary" mb={2}>{data.intro} Choose one answer for each question.</Typography>
      <Stack gap={2.5}>
        {data.items.map((item, n) => (
          <Box key={item.id} component="fieldset" sx={{ border: 0, p: 0, m: 0 }}>
            <FormLabel component="legend" sx={{ color: "text.primary", fontWeight: 600, mb: 0.5 }}>{n + 1}. {item.text}</FormLabel>
            <RadioGroup row value={answers[item.id] ?? ""} onChange={(e) => setAnswers({ ...answers, [item.id]: Number(e.target.value) })}>
              {data.options.map((o, v) => <FormControlLabel key={o} value={v} control={<Radio />} label={o} />)}
            </RadioGroup>
          </Box>
        ))}
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction="row" gap={1}>
          <Button variant="contained" size="large" disabled={!complete || busy} onClick={submit}>Submit</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </Stack>
      </Stack>
    </CardContent></Card>
  );
}
