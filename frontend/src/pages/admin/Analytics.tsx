import CheckCircleRounded from "@mui/icons-material/CheckCircleRounded";
import HelpOutlineRounded from "@mui/icons-material/HelpOutlineRounded";
import WarningRounded from "@mui/icons-material/WarningRounded";
import {
  Alert, Box, Card, CardContent, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useApi } from "../../api/client";
import { ErrorState, Loading, PageHeader, Section, titleCase } from "../../components/common";
import { severityColors } from "../../theme";

interface Kpi { name: string; value: number | null; target: number; met: boolean | null; unit: string; detail: string; higher_is_better: boolean }
interface Analytics {
  disclaimer: string; kpis: Kpi[];
  patients: { total: number; by_risk: Record<string, number> };
  alerts: { total_by_severity: Record<string, number>; open_by_severity: Record<string, number>; by_category: Record<string, number>; red_median_ack_minutes: number | null };
  escalations: { responded: number; median_response_minutes: number | null };
  ai: { responses: number; answered_from_content: number; refused_or_routed: number; by_safety_level: Record<string, number>; median_latency_ms: number | null; by_model: Record<string, number>; tokens: { input: number; output: number } };
  medications: Record<string, number>; appointments: Record<string, number>;
}

const fmt = (k: Kpi, v: number | null) => (v == null ? "—" : k.unit === "ratio" ? `${Math.round(v * 100)}%` : `${v} min`);

/** Stat tile: headline value, target, and a status shown by icon + text (not color alone). */
function KpiTile({ k }: { k: Kpi }) {
  const status = k.met == null ? { Icon: HelpOutlineRounded, label: "No data yet", c: "#475467" }
    : k.met ? { Icon: CheckCircleRounded, label: "Meets target", c: severityColors.GREEN.main }
      : { Icon: WarningRounded, label: "Below target", c: severityColors.AMBER.main };
  const pct = k.value == null ? 0 : k.unit === "ratio" ? Math.min(100, k.value * 100) : Math.min(100, (k.value / (k.target * 2)) * 100);
  const targetPct = k.unit === "ratio" ? k.target * 100 : 50;
  return (
    <Card sx={{ height: "100%" }}><CardContent>
      <Typography variant="body2" color="text.secondary" fontWeight={600}>{k.name}</Typography>
      <Typography variant="h3" component="p" fontWeight={700} mt={0.5}>{fmt(k, k.value)}</Typography>
      <Box sx={{ position: "relative", height: 8, bgcolor: "#eaecf0", borderRadius: 4, mt: 1.5 }} aria-hidden>
        <Box sx={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`, bgcolor: "primary.main", borderRadius: 4 }} />
        <Box sx={{ position: "absolute", left: `${targetPct}%`, top: -4, bottom: -4, width: 2, bgcolor: "#101828" }} />
      </Box>
      <Typography variant="body2" mt={1}>Target {k.higher_is_better ? "≥" : "≤"} {fmt(k, k.target)}</Typography>
      <Stack direction="row" gap={0.5} alignItems="center" mt={0.5}>
        <status.Icon sx={{ color: status.c, fontSize: 18 }} aria-hidden />
        <Typography variant="body2" fontWeight={600}>{status.label}</Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary">{k.detail}</Typography>
    </CardContent></Card>
  );
}

function CountTable({ title, data, label = "Count" }: { title: string; data: Record<string, number>; label?: string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <Section title={title} id={title.replace(/\W/g, "")}>
      <Table size="small">
        <TableHead><TableRow><TableCell>Item</TableCell><TableCell align="right">{label}</TableCell></TableRow></TableHead>
        <TableBody>
          {entries.length === 0 && <TableRow><TableCell colSpan={2}>No data</TableCell></TableRow>}
          {entries.map(([k, v]) => <TableRow key={k}><TableCell>{titleCase(k)}</TableCell><TableCell align="right">{v}</TableCell></TableRow>)}
        </TableBody>
      </Table>
    </Section>
  );
}

export default function AnalyticsPage() {
  const { data, error, loading, reload } = useApi<Analytics>("/analytics");
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} onRetry={reload} />;
  const ai = data.ai;
  return (
    <Stack gap={2.5}>
      <PageHeader title="Program analytics" subtitle="30-day recovery program performance against configurable BRD targets" />
      <Alert severity="info">{data.disclaimer}</Alert>
      <Grid container spacing={2}>
        {data.kpis.map((k) => <Grid item xs={12} sm={6} lg={3} key={k.name}><KpiTile k={k} /></Grid>)}
      </Grid>
      <Grid container spacing={2}>
        {[
          ["Enrolled patients", data.patients.total],
          ["Open alerts", Object.values(data.alerts.open_by_severity).reduce((a, b) => a + b, 0)],
          ["RED median time to acknowledge", data.alerts.red_median_ack_minutes != null ? `${data.alerts.red_median_ack_minutes} min` : "—"],
          ["Escalation median response", data.escalations.median_response_minutes != null ? `${data.escalations.median_response_minutes} min` : "—"],
          ["Assistant responses", ai.responses],
          ["Answered from approved content", ai.responses ? `${Math.round((ai.answered_from_content / ai.responses) * 100)}%` : "—"],
          ["Assistant median latency", ai.median_latency_ms != null ? `${ai.median_latency_ms} ms` : "—"],
          ["LLM tokens (in / out)", `${ai.tokens.input} / ${ai.tokens.output}`],
        ].map(([label, v]) => (
          <Grid item xs={6} md={3} key={label as string}>
            <Card><CardContent>
              <Typography variant="body2" color="text.secondary">{label}</Typography>
              <Typography variant="h5" component="p">{v}</Typography>
            </CardContent></Card>
          </Grid>
        ))}
      </Grid>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}><CountTable title="Patients by current risk" data={data.patients.by_risk} label="Patients" /></Grid>
        <Grid item xs={12} md={4}><CountTable title="Alerts by category (all time)" data={data.alerts.by_category} /></Grid>
        <Grid item xs={12} md={4}><CountTable title="Alerts by severity (all time)" data={data.alerts.total_by_severity} /></Grid>
        <Grid item xs={12} md={4}><CountTable title="Assistant responses by safety level" data={ai.by_safety_level} /></Grid>
        <Grid item xs={12} md={4}><CountTable title="Assistant responses by model" data={ai.by_model} /></Grid>
        <Grid item xs={12} md={4}><CountTable title="Medication dose events" data={data.medications} /></Grid>
      </Grid>
    </Stack>
  );
}
