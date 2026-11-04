import ArrowBackRounded from "@mui/icons-material/ArrowBackRounded";
import ArrowForwardRounded from "@mui/icons-material/ArrowForwardRounded";
import PhoneInTalkRounded from "@mui/icons-material/PhoneInTalkRounded";
import {
  Alert, AlertTitle, Box, Button, Card, CardContent, Checkbox, FormControlLabel, FormGroup, LinearProgress, Radio,
  RadioGroup, Slider, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { CheckinQuestion, Severity } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, Loading, SeverityChip } from "../../components/common";

type Answers = Record<string, unknown>;
interface Result { risk_level: Severity; patient_message: string; emergency: boolean; rules_triggered: { name: string; severity: string }[] }

export default function Checkin() {
  const { user } = useAuth();
  const pid = user!.patient_id;
  const { data: questions, error, loading } = useApi<CheckinQuestion[]>(`/patients/${pid}/checkin-questions`);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Answers>({ new_symptoms: ["NONE"], temperature_unit: "F" });
  const [result, setResult] = useState<Result | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (loading) return <Loading />;
  if (error || !questions) return <ErrorState message={error ?? "Unavailable"} />;

  if (result) return <CheckinResult result={result} />;

  const q = questions[step];
  const last = step === questions.length - 1;
  const value = answers[q.key];
  const canNext = !q.required || (value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0));
  const set = (v: unknown) => setAnswers((a) => ({ ...a, [q.key]: v }));

  async function submit() {
    setBusy(true);
    setSubmitError(null);
    try {
      const clean = Object.fromEntries(Object.entries(answers).filter(([, v]) => v !== "" && v !== undefined));
      setResult(await api<Result>(`/patients/${pid}/checkins`, { body: { answers: clean } }));
    } catch (e) {
      setSubmitError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack gap={2} maxWidth={640} mx="auto">
      <Box>
        <Typography variant="h4" component="h1">Daily check-in</Typography>
        <Typography color="text.secondary">About 2 minutes · Question {step + 1} of {questions.length}</Typography>
        <LinearProgress variant="determinate" value={((step + 1) / questions.length) * 100} sx={{ mt: 1.5, height: 8, borderRadius: 4 }} aria-label="Check-in progress" />
      </Box>
      <Alert severity="info" icon={<PhoneInTalkRounded />}>
        Having chest pain, trouble breathing or heavy bleeding? Don't wait — <strong>call 911</strong>.
      </Alert>
      <Card>
        <CardContent sx={{ p: { xs: 2.5, sm: 3 } }}>
          <Typography variant="h6" component="h2" id="q-label" gutterBottom>{q.text}</Typography>
          {q.help_text && <Typography variant="body2" color="text.secondary" mb={2}>{q.help_text}</Typography>}
          <QuestionInput q={q} value={value} onChange={set} answers={answers} setAnswers={setAnswers} />
          {!q.required && <Typography variant="caption" color="text.secondary" display="block" mt={2}>Optional</Typography>}
        </CardContent>
      </Card>
      {submitError && <Alert severity="error">{submitError}</Alert>}
      <Stack direction="row" justifyContent="space-between">
        <Button startIcon={<ArrowBackRounded />} disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
        {last ? (
          <Button variant="contained" size="large" onClick={submit} disabled={busy || !canNext}>{busy ? "Submitting…" : "Submit check-in"}</Button>
        ) : (
          <Button variant="contained" size="large" endIcon={<ArrowForwardRounded />} disabled={!canNext} onClick={() => setStep(step + 1)}>
            {q.required || value !== undefined ? "Next" : "Skip"}
          </Button>
        )}
      </Stack>
    </Stack>
  );
}

function QuestionInput({ q, value, onChange, answers, setAnswers }: {
  q: CheckinQuestion; value: unknown; onChange: (v: unknown) => void; answers: Answers; setAnswers: (fn: (a: Answers) => Answers) => void;
}) {
  switch (q.answer_type) {
    case "SCALE": {
      const v = typeof value === "number" ? value : undefined;
      return (
        <Box px={1}>
          <Typography variant="h3" textAlign="center" color={v === undefined ? "text.disabled" : v >= 7 ? "error.main" : v >= 4 ? "warning.main" : "success.main"} aria-live="polite">
            {v ?? "–"}
          </Typography>
          <Slider value={v ?? 0} min={q.min_value ?? 0} max={q.max_value ?? 10} step={1} marks
            valueLabelDisplay="auto" onChange={(_, n) => onChange(n as number)} aria-labelledby="q-label" />
          <Stack direction="row" justifyContent="space-between"><Typography variant="caption">No pain</Typography><Typography variant="caption">Worst pain</Typography></Stack>
        </Box>
      );
    }
    case "CHOICE":
      return (
        <RadioGroup value={value ?? ""} onChange={(e) => onChange(e.target.value)} aria-labelledby="q-label">
          {q.options.map((o) => (
            <FormControlLabel key={o.value} value={o.value} control={<Radio />} label={o.label}
              sx={{ border: "1px solid #e4e7ec", borderRadius: 2, mx: 0, mb: 1, px: 1, py: 0.5, bgcolor: value === o.value ? "#f0fdfa" : undefined }} />
          ))}
        </RadioGroup>
      );
    case "MULTI": {
      const sel = (Array.isArray(value) ? value : []) as string[];
      const toggle = (v: string) => {
        if (v === "NONE") return onChange(["NONE"]);
        const next = sel.includes(v) ? sel.filter((x) => x !== v) : [...sel.filter((x) => x !== "NONE"), v];
        onChange(next.length ? next : ["NONE"]);
      };
      return (
        <FormGroup aria-labelledby="q-label">
          {q.options.map((o) => (
            <FormControlLabel key={o.value} control={<Checkbox checked={sel.includes(o.value)} onChange={() => toggle(o.value)} />} label={o.label} />
          ))}
        </FormGroup>
      );
    }
    case "NUMBER":
      return (
        <Stack direction="row" gap={2} alignItems="center">
          <TextField type="number" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            inputProps={{ min: q.key === "temperature" && answers.temperature_unit === "C" ? 34 : q.min_value ?? undefined, step: q.key === "temperature" ? 0.1 : 1, "aria-labelledby": "q-label" }}
            sx={{ maxWidth: 180 }} />
          {q.key === "temperature" ? (
            <ToggleButtonGroup exclusive size="small" value={answers.temperature_unit ?? "F"}
              onChange={(_, u) => u && setAnswers((a) => ({ ...a, temperature_unit: u }))} aria-label="Temperature unit">
              <ToggleButton value="F">°F</ToggleButton><ToggleButton value="C">°C</ToggleButton>
            </ToggleButtonGroup>
          ) : <Typography>{q.unit}</Typography>}
        </Stack>
      );
    case "BOOLEAN":
      return <FormControlLabel control={<Switch checked={!!value} onChange={(e) => onChange(e.target.checked)} />} label={value ? "Yes" : "No"} />;
    default:
      return <TextField multiline minRows={3} fullWidth value={value ?? ""} onChange={(e) => onChange(e.target.value)}
        placeholder="Optional" inputProps={{ maxLength: 2000, "aria-labelledby": "q-label" }} />;
  }
}

function CheckinResult({ result }: { result: Result }) {
  const sev = result.risk_level;
  return (
    <Stack gap={2} maxWidth={640} mx="auto">
      <Typography variant="h4" component="h1">Check-in submitted</Typography>
      <Alert severity={sev === "RED" ? "error" : sev === "AMBER" ? "warning" : "success"} role="alert"
        sx={{ fontSize: 17 }} icon={false}>
        <AlertTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}><SeverityChip level={sev} long /></AlertTitle>
        {result.patient_message}
      </Alert>
      {result.emergency && (
        <Button href="tel:911" variant="contained" color="error" size="large" startIcon={<PhoneInTalkRounded />}>Call 911</Button>
      )}
      {result.rules_triggered.length > 0 && (
        <Card><CardContent>
          <Typography variant="subtitle1" gutterBottom>What your care team will review</Typography>
          {result.rules_triggered.map((r) => <Typography key={r.name}>• {r.name}</Typography>)}
          <Typography variant="body2" color="text.secondary" mt={1}>These checks come from your surgeon's approved warning signs.</Typography>
        </CardContent></Card>
      )}
      <Button component={RouterLink} to="/patient" variant="outlined">Back to home</Button>
    </Stack>
  );
}
