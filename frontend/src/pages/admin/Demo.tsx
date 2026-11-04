import CancelRounded from "@mui/icons-material/CancelRounded";
import CheckCircleRounded from "@mui/icons-material/CheckCircleRounded";
import PlayArrowRounded from "@mui/icons-material/PlayArrowRounded";
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Grid, Stack, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, Loading, PageHeader } from "../../components/common";

interface Scenario { scenario: number; title: string; description: string }
interface Step { step: string; expected: unknown; actual: unknown; passed: boolean; detail?: unknown }
interface Result extends Scenario { passed: boolean; steps: Step[]; patient_name: string; patient_id: string }

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export default function DemoPage() {
  const { user } = useAuth();
  const { data, error, loading } = useApi<Scenario[]>("/demo/scenarios");
  const [results, setResults] = useState<Record<number, Result>>({});
  const [running, setRunning] = useState<number | "all" | null>(null);
  const [jobs, setJobs] = useState<Record<string, number> | null>(null);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;

  async function run(n: number) {
    setRunning(n);
    try {
      const r = await api<Result>(`/demo/scenarios/${n}/run`, { method: "POST" });
      setResults((x) => ({ ...x, [n]: r }));
    } finally { setRunning(null); }
  }
  async function runAll() {
    setRunning("all");
    try {
      const r = await api<{ results: Result[] }>("/demo/scenarios/run-all", { method: "POST" });
      setResults(Object.fromEntries(r.results.map((x) => [x.scenario, x])));
    } finally { setRunning(null); }
  }
  const done = Object.values(results);

  return (
    <Stack gap={2.5}>
      <PageHeader title="Automated demo scenarios"
        subtitle="Each scenario creates a fresh synthetic patient and runs the real agents, rules engine and workflows, then verifies the outcome."
        action={<Stack direction="row" gap={1}>
          {user!.role === "ADMIN" && <Button variant="outlined" onClick={async () => setJobs(await api("/admin/jobs/run", { method: "POST" }))}>Run scheduled jobs</Button>}
          <Button variant="contained" startIcon={running === "all" ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRounded />} onClick={runAll} disabled={running !== null}>Run all 8</Button>
        </Stack>} />
      {jobs && <Alert severity="info" onClose={() => setJobs(null)}>Jobs: {Object.entries(jobs).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</Alert>}
      {done.length > 0 && (
        <Alert severity={done.every((r) => r.passed) ? "success" : "error"}>
          {done.filter((r) => r.passed).length} of {done.length} scenarios passed. Created alerts appear on the nurse worklist.
        </Alert>
      )}
      <Grid container spacing={2}>
        {data.map((s) => {
          const r = results[s.scenario];
          return (
            <Grid item xs={12} md={6} key={s.scenario}>
              <Card sx={{ height: "100%", borderColor: r ? (r.passed ? "success.main" : "error.main") : undefined }}>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" gap={1} alignItems="flex-start">
                    <Box>
                      <Typography variant="overline" color="text.secondary">Scenario {s.scenario}</Typography>
                      <Typography variant="subtitle1">{s.title}</Typography>
                      <Typography variant="body2" color="text.secondary">{s.description}</Typography>
                    </Box>
                    <Button size="small" variant="outlined" onClick={() => run(s.scenario)} disabled={running !== null}
                      startIcon={running === s.scenario ? <CircularProgress size={14} /> : <PlayArrowRounded />}>Run</Button>
                  </Stack>
                  {r && (
                    <Box mt={2}>
                      <Chip size="small" color={r.passed ? "success" : "error"} label={r.passed ? "PASSED" : "FAILED"} sx={{ mb: 1 }} />
                      <Typography variant="caption" color="text.secondary" display="block" mb={1}>Patient: {r.patient_name}</Typography>
                      {r.steps.map((st, i) => (
                        <Stack key={i} direction="row" gap={1} alignItems="flex-start" mb={0.5}>
                          {st.passed ? <CheckCircleRounded color="success" fontSize="small" aria-label="passed" /> : <CancelRounded color="error" fontSize="small" aria-label="failed" />}
                          <Box>
                            <Typography variant="body2" fontWeight={600}>{st.step}</Typography>
                            <Typography variant="caption" color="text.secondary">expected {show(st.expected)} · actual {show(st.actual)}</Typography>
                            {st.detail != null && <Typography variant="caption" display="block" color="text.secondary" sx={{ wordBreak: "break-word" }}>{show(st.detail).slice(0, 240)}</Typography>}
                          </Box>
                        </Stack>
                      ))}
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>
    </Stack>
  );
}
