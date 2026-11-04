import AccountTreeRounded from "@mui/icons-material/AccountTreeRounded";
import CableRounded from "@mui/icons-material/CableRounded";
import ContentCopyRounded from "@mui/icons-material/ContentCopyRounded";
import KeyRounded from "@mui/icons-material/KeyRounded";
import ListAltRounded from "@mui/icons-material/ListAltRounded";
import OutboxRounded from "@mui/icons-material/OutboxRounded";
import PlayArrowRounded from "@mui/icons-material/PlayArrowRounded";
import ScienceRounded from "@mui/icons-material/ScienceRounded";
import TipsAndUpdatesRounded from "@mui/icons-material/TipsAndUpdatesRounded";
import {
  Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, Grid,
  IconButton, InputLabel, MenuItem, Select, Stack, Switch, Tab, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Tabs, Tooltip, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { ErrorState, fmtDateTime, Loading, PageHeader, Section, timeAgo } from "../../components/common";
import { FlowDiagram, type Workflow } from "../../components/FlowDiagram";

type Status = "PROCESSED" | "PARTIAL" | "REJECTED";
interface UseCase {
  id: string; title: string; status: "LIVE" | "PARTIAL" | "PLANNED"; channel: string; manual_today: string; automated: string;
  standards: string[]; source_systems: string[]; data: string[]; endpoint: string;
}
interface Source {
  id: string; slug: string; name: string; channel: string; description: string; is_active: boolean; key_prefix: string;
  key_rotated_at: string | null; last_message_at: string | null; endpoint: string; counts: Partial<Record<Status, number>>;
  dev_key: string | null;
}
interface Scenario { key: string; title: string; source: string; content_type: string; expect: string }
interface Overview {
  window_days: number; use_cases: UseCase[]; standards: { name: string; what: string }[]; pipeline: Workflow; outbound_pipeline: Workflow;
  outbound: { destination: string; mode: "HTTP" | "SIMULATED"; url_configured: boolean; counts: Record<string, number>; max_attempts: number };
  sources: Source[]; scenarios: Scenario[]; patients: { mrn: string; name: string; procedure: string | null }[];
}
interface Msg {
  id: string; received_at: string; source: string; source_slug: string; channel: string; message_type: string;
  external_id: string; status: Status; patient_mrn: string | null; result: Record<string, unknown>; errors: string[];
  processing_ms: number | null; simulated: boolean; payload?: string;
}
interface SimResult { scenario: string; title: string; content_type: string; raw: string; ack: string | null; message: Msg; duplicate: boolean }

const STATUS_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  PROCESSED: "success", PARTIAL: "warning", REJECTED: "error",
};
const USE_CASE_STATUS = {
  LIVE: { label: "Live in POC", color: "success" as const },
  PARTIAL: { label: "Partly live", color: "warning" as const },
  PLANNED: { label: "Planned", color: "default" as const },
};
const CHANNEL_LABEL: Record<string, string> = {
  FHIR: "FHIR R4", HL7V2: "HL7 v2", DEVICE: "Device JSON", PHARMACY: "NCPDP SCRIPT", OUTBOUND: "Outbound FHIR", APP: "Patient app",
};
const NAMES = { integration_intake: "Integration Intake", alerting: "Alert / Escalation", transport: "Transport Coordination" };

const Mono = ({ children, maxHeight = 320 }: { children: string; maxHeight?: number }) => (
  <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: "#101828", color: "#e4e7ec", borderRadius: 1.5, fontSize: 12, overflow: "auto", maxHeight, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
    {children}
  </Box>
);

export default function IntegrationsPage() {
  const [tab, setTab] = useState(0);
  const overview = useApi<Overview>("/admin/integrations");
  const [logKey, setLogKey] = useState(0);
  if (overview.loading && !overview.data) return <Loading />;
  if (overview.error || !overview.data) return <ErrorState message={overview.error ?? ""} onRetry={overview.reload} />;
  const data = overview.data;
  const refresh = () => { overview.reload(); setLogKey((k) => k + 1); };

  return (
    <Stack gap={2}>
      <PageHeader title="Integrations" subtitle="Receive post-surgical data automatically from EHRs, devices and wearables instead of typing it in." />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile aria-label="Integration sections">
        <Tab icon={<TipsAndUpdatesRounded />} iconPosition="start" label="Use cases & inputs" />
        <Tab icon={<AccountTreeRounded />} iconPosition="start" label="How it works" />
        <Tab icon={<CableRounded />} iconPosition="start" label={`Sources (${data.sources.length})`} />
        <Tab icon={<ListAltRounded />} iconPosition="start" label="Message log" />
        <Tab icon={<ScienceRounded />} iconPosition="start" label="Try it" />
        <Tab icon={<OutboxRounded />} iconPosition="start" label="Outbound to EHR" />
      </Tabs>
      {tab === 0 && <UseCasesTab cases={data.use_cases} />}
      {tab === 1 && <HowItWorksTab data={data} />}
      {tab === 2 && <SourcesTab sources={data.sources} days={data.window_days} onChange={refresh} />}
      {tab === 3 && <MessageLogTab key={logKey} sources={data.sources} />}
      {tab === 4 && <TryItTab data={data} onSent={refresh} />}
      {tab === 5 && <OutboundTab data={data} onChange={refresh} />}
    </Stack>
  );
}

function UseCasesTab({ cases }: { cases: UseCase[] }) {
  const live = cases.filter((c) => c.status !== "PLANNED").length;
  return (
    <Stack gap={2}>
      <Alert severity="info">
        In US healthcare, almost everything a recovery program needs after surgery already exists electronically: the
        hospital EHR sends discharge events (HL7 v2 ADT) through its interface engine and exposes discharge medications,
        appointments and vitals through FHIR R4 APIs, and remote-monitoring devices upload readings to their vendor's
        cloud. Instead of staff or patients re-typing that data, these feeds post it here. <strong>{live} of {cases.length}</strong> use
        cases are implemented in this POC.
      </Alert>
      <Grid container spacing={2}>
        {cases.map((c) => (
          <Grid item xs={12} lg={6} key={c.id}>
            <Card sx={{ height: "100%" }}><CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
                <Typography variant="h6" component="h2">{c.title}</Typography>
                <Chip size="small" label={USE_CASE_STATUS[c.status].label} color={USE_CASE_STATUS[c.status].color}
                  variant={c.status === "PLANNED" ? "outlined" : "filled"} />
              </Stack>
              <Grid container spacing={1.5} mt={0.25}>
                <Grid item xs={12} sm={6}>
                  <Box sx={{ p: 1.25, bgcolor: "#f9fafb", border: "1px solid #eaecf0", borderRadius: 1.5, height: "100%" }}>
                    <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase">Today (manual)</Typography>
                    <Typography variant="body2">{c.manual_today}</Typography>
                  </Box>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <Box sx={{ p: 1.25, bgcolor: "#ecfdf3", border: "1px solid #abefc6", borderRadius: 1.5, height: "100%" }}>
                    <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase">Automated</Typography>
                    <Typography variant="body2">{c.automated}</Typography>
                  </Box>
                </Grid>
              </Grid>
              <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase" display="block" mt={1.5}>Input data</Typography>
              <Stack direction="row" gap={0.5} flexWrap="wrap">{c.data.map((d) => <Chip key={d} size="small" label={d} />)}</Stack>
              <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase" display="block" mt={1.5}>Standards</Typography>
              <Stack direction="row" gap={0.5} flexWrap="wrap">{c.standards.map((d) => <Chip key={d} size="small" variant="outlined" label={d} />)}</Stack>
              <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase" display="block" mt={1.5}>Typical source systems</Typography>
              <Box component="ul" sx={{ m: 0, pl: 2.5 }}>{c.source_systems.map((s) => <li key={s}><Typography variant="body2">{s}</Typography></li>)}</Box>
              {c.endpoint !== "—" && <Typography variant="body2" mt={1}>Endpoint: <code>{c.endpoint}</code></Typography>}
            </CardContent></Card>
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}

function HowItWorksTab({ data }: { data: Overview }) {
  return (
    <Stack gap={2}>
      <FlowDiagram wf={data.pipeline} names={NAMES} />
      <FlowDiagram wf={data.outbound_pipeline} names={NAMES} />
      <Grid container spacing={2}>
        <Grid item xs={12} md={7}>
          <Section title="Standards used in US healthcare">
            <Table size="small">
              <TableBody>
                {data.standards.map((s) => (
                  <TableRow key={s.name}>
                    <TableCell sx={{ width: 190, verticalAlign: "top" }}><Typography variant="body2" fontWeight={700}>{s.name}</Typography></TableCell>
                    <TableCell>{s.what}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        </Grid>
        <Grid item xs={12} md={5}>
          <Section title="Safety and security rules">
            <Box component="ul" sx={{ m: 0, pl: 2.5, "& li": { mb: 0.75 } }}>
              {[
                "Each sending system has its own key, stored only as a hash. Keys can be rotated or the source disabled at any time.",
                "Messages are matched to enrolled patients by MRN. A message can never create an enrollment.",
                "Every message is logged with its raw payload encrypted at rest; opening a payload is audited.",
                "Re-delivered messages (same message id) are recognised and not applied twice.",
                "Readings outside physiologically plausible ranges are rejected, and readings older than 24 hours are stored but never page the care team.",
                "Alert thresholds come only from surgeon-approved warning protocols. No AI is involved in intake.",
                "New medications from the EHR get no missed-dose guidance until the doctor approves it; a reconciliation task is created for the doctor.",
                "Production: SMART Backend Services (OAuth 2.0 + signed JWT), mutual TLS or a VPN to the interface engine, and a BAA with every vendor.",
              ].map((t) => <li key={t}><Typography variant="body2">{t}</Typography></li>)}
            </Box>
          </Section>
        </Grid>
      </Grid>
    </Stack>
  );
}

function curlFor(s: Source) {
  const key = s.dev_key ?? "<integration key>";
  const origin = window.location.origin;
  if (s.channel === "HL7V2")
    return `printf 'MSH|^~\\\\&|EHR|HOSP|RC|POC|20261104080000||ORU^R01|MSG0001|P|2.5.1\\rPID|1||SYN-100200^^^HOSP^MR\\rOBX|1|NM|8310-5^Body temperature^LN||99.1|[degF]|||||F\\r' \\
  | curl -X POST ${origin}${s.endpoint} -H 'X-Integration-Key: ${key}' -H 'Content-Type: text/plain' --data-binary @-`;
  if (s.channel === "PHARMACY")
    return `curl -X POST ${origin}${s.endpoint} -H 'X-Integration-Key: ${key}' -H 'Content-Type: application/xml' \\
  -d '<Message><Header><MessageID>RXF-0001</MessageID></Header><Body><RxFill><FillStatus><Dispensed/></FillStatus>
  <Patient><HumanPatient><Identification><MedicalRecordIdentificationNumberEHR>SYN-100200</MedicalRecordIdentificationNumberEHR>
  </Identification></HumanPatient></Patient><MedicationDispensed><DrugDescription>Apixaban 2.5 mg tablet</DrugDescription>
  </MedicationDispensed></RxFill></Body></Message>'`;
  if (s.channel === "FHIR")
    return `curl -X POST ${origin}${s.endpoint} -H 'X-Integration-Key: ${key}' -H 'Content-Type: application/fhir+json' \\
  -d '{"resourceType":"Bundle","id":"b-0001","type":"collection","entry":[{"resource":{"resourceType":"Observation","status":"final",
  "subject":{"identifier":{"value":"SYN-100200"}},"code":{"coding":[{"system":"http://loinc.org","code":"8310-5"}]},
  "effectiveDateTime":"${new Date().toISOString()}","valueQuantity":{"value":37.2,"code":"Cel"}}}]}'`;
  return `curl -X POST ${origin}${s.endpoint} -H 'X-Integration-Key: ${key}' -H 'Content-Type: application/json' \\
  -d '{"message_id":"rpm-0001","patient":{"mrn":"SYN-100200"},"device":{"type":"THERMOMETER"},
  "readings":[{"type":"TEMPERATURE","value":99.1,"unit":"[degF]","measured_at":"${new Date().toISOString()}"}]}'`;
}

function copy(text: string) {
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

function SourcesTab({ sources, days, onChange }: { sources: Source[]; days: number; onChange: () => void }) {
  const [newKey, setNewKey] = useState<{ name: string; key: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [example, setExample] = useState<Source | null>(null);

  async function rotate(s: Source) {
    if (!window.confirm(`Issue a new key for ${s.name}? The current key stops working immediately.`)) return;
    try {
      const r = await api<{ key: string }>(`/admin/integrations/sources/${s.id}/rotate-key`, { method: "POST" });
      setNewKey({ name: s.name, key: r.key });
      onChange();
    } catch (e) { setErr((e as Error).message); }
  }
  async function toggle(s: Source) {
    try {
      await api(`/admin/integrations/sources/${s.id}/active?active=${!s.is_active}`, { method: "POST" });
      onChange();
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <Stack gap={2}>
      {err && <Alert severity="error" onClose={() => setErr(null)}>{err}</Alert>}
      <Alert severity="info">Each sending system authenticates with its own <code>X-Integration-Key</code>. Counts cover the last {days} days.</Alert>
      <Card>
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow>
              <TableCell>Source</TableCell><TableCell>Channel</TableCell><TableCell>Endpoint</TableCell><TableCell>Key</TableCell>
              <TableCell>Last message</TableCell><TableCell align="right">Processed / partial / rejected</TableCell><TableCell>Active</TableCell><TableCell />
            </TableRow></TableHead>
            <TableBody>
              {sources.map((s) => (
                <TableRow key={s.id} hover>
                  <TableCell sx={{ maxWidth: 300 }}>
                    <Typography variant="body2" fontWeight={600}>{s.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{s.description}</Typography>
                  </TableCell>
                  <TableCell><Chip size="small" label={CHANNEL_LABEL[s.channel] ?? s.channel} /></TableCell>
                  <TableCell><code>POST {s.endpoint}</code></TableCell>
                  <TableCell>
                    <code>{s.key_prefix}…</code>
                    <Typography variant="caption" display="block" color="text.secondary">
                      {s.key_rotated_at ? `rotated ${timeAgo(s.key_rotated_at)}` : "development key"}
                    </Typography>
                  </TableCell>
                  <TableCell>{s.last_message_at ? timeAgo(s.last_message_at) : "—"}</TableCell>
                  <TableCell align="right">{s.counts.PROCESSED ?? 0} / {s.counts.PARTIAL ?? 0} / {s.counts.REJECTED ?? 0}</TableCell>
                  <TableCell><Switch checked={s.is_active} onChange={() => toggle(s)} inputProps={{ "aria-label": `Active ${s.name}` }} /></TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    <Button size="small" onClick={() => setExample(s)}>Example</Button>
                    <Button size="small" startIcon={<KeyRounded />} onClick={() => rotate(s)}>Rotate key</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      <Dialog open={!!newKey} onClose={() => setNewKey(null)} maxWidth="sm" fullWidth>
        <DialogTitle>New key for {newKey?.name}</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>Copy it now. It is stored only as a hash and will not be shown again.</Alert>
          <Stack direction="row" alignItems="center" gap={1}>
            <Box component="code" sx={{ p: 1, bgcolor: "#f2f4f7", borderRadius: 1, flex: 1, wordBreak: "break-all" }}>{newKey?.key}</Box>
            <Tooltip title="Copy"><IconButton onClick={() => newKey && copy(newKey.key)} aria-label="Copy key"><ContentCopyRounded /></IconButton></Tooltip>
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setNewKey(null)}>Done</Button></DialogActions>
      </Dialog>

      <Dialog open={!!example} onClose={() => setExample(null)} maxWidth="md" fullWidth>
        <DialogTitle>Send a test message to {example?.name}</DialogTitle>
        <DialogContent>
          {example && (
            <Stack gap={1.5}>
              {!example.dev_key && <Alert severity="info">Replace <code>&lt;integration key&gt;</code> with the key issued when you rotated it.</Alert>}
              <Mono>{curlFor(example)}</Mono>
              <Button startIcon={<ContentCopyRounded />} onClick={() => copy(curlFor(example))} sx={{ alignSelf: "flex-start" }}>Copy</Button>
            </Stack>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setExample(null)}>Close</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}

/** One-line description of what a message did, from its result counts. */
function resultSummary(m: Msg): string {
  const r = m.result as Record<string, any>;
  const parts: string[] = [];
  if (r.discharge_date) parts.push(r.discharge_date === "unchanged" ? "discharge confirmed" : `discharge → ${r.discharge_date.to}`);
  if (r.medications) parts.push(`meds +${r.medications.created} / ~${r.medications.updated}`);
  if (r.appointments) parts.push(`appts +${r.appointments.created} / ~${r.appointments.updated}`);
  if (r.readings) parts.push(`${r.readings.stored} reading(s) · ${r.readings.risk_level}${r.readings.rules_triggered?.length ? ` (${r.readings.rules_triggered.join(", ")})` : ""}`);
  if (r.warnings?.length) parts.push(`${r.warnings.length} warning(s)`);
  if (!parts.length && m.errors.length) return m.errors[0];
  return parts.join(" · ") || "—";
}

function MessageLogTab({ sources }: { sources: Source[] }) {
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const q = new URLSearchParams({ limit: "200", ...(status && { status }), ...(source && { source }) });
  const { data, error, loading, reload } = useApi<Msg[]>(`/admin/integrations/messages?${q}`, [status, source]);
  const [detail, setDetail] = useState<Msg | null>(null);

  async function open(id: string) {
    setDetail(await api<Msg>(`/admin/integrations/messages/${id}`));
  }

  return (
    <Stack gap={2}>
      <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
        {["", "PROCESSED", "PARTIAL", "REJECTED"].map((s) => (
          <Chip key={s || "all"} label={s || "All statuses"} clickable color={status === s ? "primary" : "default"} onClick={() => setStatus(s)} />
        ))}
        <FormControl size="small" sx={{ minWidth: 240 }}>
          <InputLabel id="src">Source</InputLabel>
          <Select labelId="src" label="Source" value={source} onChange={(e) => setSource(e.target.value)}>
            <MenuItem value="">All sources</MenuItem>
            {sources.map((s) => <MenuItem key={s.slug} value={s.slug}>{s.name}</MenuItem>)}
          </Select>
        </FormControl>
        <Button onClick={reload}>Refresh</Button>
      </Stack>
      {loading && !data && <Loading />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Received</TableCell><TableCell>Source</TableCell><TableCell>Type</TableCell><TableCell>Status</TableCell>
                <TableCell>MRN</TableCell><TableCell>What happened</TableCell><TableCell align="right">ms</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {data.length === 0 && <TableRow><TableCell colSpan={7}>No messages yet. Use “Try it” to send one.</TableCell></TableRow>}
                {data.map((m) => (
                  <TableRow key={m.id} hover sx={{ cursor: "pointer" }} onClick={() => open(m.id)}>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDateTime(m.received_at)}</TableCell>
                    <TableCell>{m.source}{m.simulated && <Chip size="small" label="simulated" sx={{ ml: 0.5 }} variant="outlined" />}</TableCell>
                    <TableCell><code>{m.message_type}</code></TableCell>
                    <TableCell><Chip size="small" label={m.status} color={STATUS_COLOR[m.status]} /></TableCell>
                    <TableCell>{m.patient_mrn ?? "—"}</TableCell>
                    <TableCell>{resultSummary(m)}</TableCell>
                    <TableCell align="right">{m.processing_ms ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
      <Dialog open={!!detail} onClose={() => setDetail(null)} maxWidth="md" fullWidth>
        {detail && (
          <>
            <DialogTitle>{detail.message_type} from {detail.source}</DialogTitle>
            <DialogContent>
              <MessageDetail m={detail} />
              {detail.payload && (
                <>
                  <Typography variant="subtitle2" mt={2} mb={0.5}>Raw payload (contains PHI; this view is audited)</Typography>
                  <Mono>{detail.payload.replace(/\r/g, "\n")}</Mono>
                </>
              )}
            </DialogContent>
            <DialogActions><Button onClick={() => setDetail(null)}>Close</Button></DialogActions>
          </>
        )}
      </Dialog>
    </Stack>
  );
}

function MessageDetail({ m }: { m: Msg }) {
  const warnings = ((m.result as { warnings?: string[] }).warnings) ?? [];
  return (
    <Stack gap={1.5}>
      <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
        <Chip label={m.status} color={STATUS_COLOR[m.status]} />
        <Typography variant="body2">Message id <code>{m.external_id}</code> · MRN {m.patient_mrn ?? "not matched"} · {m.processing_ms ?? "—"} ms</Typography>
      </Stack>
      <Typography variant="body2"><strong>What happened:</strong> {resultSummary(m)}</Typography>
      {m.errors.length > 0 && <Alert severity={m.status === "REJECTED" ? "error" : "warning"}><Box component="ul" sx={{ m: 0, pl: 2 }}>{m.errors.map((e) => <li key={e}>{e}</li>)}</Box></Alert>}
      {warnings.length > 0 && <Alert severity="warning"><Box component="ul" sx={{ m: 0, pl: 2 }}>{warnings.map((e) => <li key={e}>{e}</li>)}</Box></Alert>}
      <Mono maxHeight={200}>{JSON.stringify(m.result, null, 2)}</Mono>
    </Stack>
  );
}

function TryItTab({ data, onSent }: { data: Overview; onSent: () => void }) {
  const [mrn, setMrn] = useState(data.patients[0]?.mrn ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<SimResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const sourceName = Object.fromEntries(data.sources.map((s) => [s.slug, s.name]));

  async function send(key: string) {
    setBusy(key); setErr(null);
    try {
      setResult(await api<SimResult>("/admin/integrations/simulate", { body: { scenario: key, mrn } }));
      onSent();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <Stack gap={2}>
      <Alert severity="warning">
        Simulated messages run through the <strong>real</strong> pipeline: they update the chosen synthetic patient's record and can
        raise real care-team alerts. They are marked “simulated” in the message log.
      </Alert>
      <FormControl size="small" sx={{ maxWidth: 420 }}>
        <InputLabel id="pt">Patient</InputLabel>
        <Select labelId="pt" label="Patient" value={mrn} onChange={(e) => setMrn(e.target.value)}>
          {data.patients.map((p) => <MenuItem key={p.mrn} value={p.mrn}>{p.mrn} · {p.name}{p.procedure ? ` · ${p.procedure}` : ""}</MenuItem>)}
        </Select>
      </FormControl>
      <Grid container spacing={1.5}>
        {data.scenarios.map((s) => (
          <Grid item xs={12} sm={6} lg={3} key={s.key}>
            <Card variant="outlined" sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <CardContent sx={{ flex: 1 }}>
                <Typography variant="caption" color="text.secondary">{sourceName[s.source] ?? s.source}</Typography>
                <Typography fontWeight={700}>{s.title}</Typography>
                <Typography variant="body2" color="text.secondary" mt={0.5}>Expected: {s.expect}</Typography>
              </CardContent>
              <Box sx={{ px: 2, pb: 2 }}>
                <Button variant="contained" size="small" startIcon={<PlayArrowRounded />} disabled={!mrn || !!busy} onClick={() => send(s.key)}>
                  {busy === s.key ? "Sending…" : "Send"}
                </Button>
              </Box>
            </Card>
          </Grid>
        ))}
      </Grid>
      {err && <Alert severity="error">{err}</Alert>}
      {result && (
        <Section title={`Result: ${result.title}`}>
          <MessageDetail m={result.message} />
          <Grid container spacing={2} mt={0}>
            <Grid item xs={12} md={result.ack ? 7 : 12}>
              <Typography variant="subtitle2" mb={0.5}>Message sent ({result.content_type})</Typography>
              <Mono>{result.raw.replace(/\r/g, "\n")}</Mono>
            </Grid>
            {result.ack && (
              <Grid item xs={12} md={5}>
                <Typography variant="subtitle2" mb={0.5}>{result.content_type === "text/plain" ? "HL7 ACK" : "NCPDP Status"} returned to the sender</Typography>
                <Mono>{result.ack.replace(/\r/g, "\n")}</Mono>
              </Grid>
            )}
          </Grid>
        </Section>
      )}
    </Stack>
  );
}

interface OutMsg {
  id: string; created_at: string; destination: string; resource_type: string; related_type: string | null; patient_mrn: string | null;
  status: "PENDING" | "SENT" | "FAILED"; delivery_mode: string | null; attempts: number; next_attempt_at: string | null;
  last_error: string | null; response_status: number | null; sent_at: string | null; payload?: string;
}
const OUT_COLOR: Record<string, "success" | "warning" | "error"> = { SENT: "success", PENDING: "warning", FAILED: "error" };

function OutboundTab({ data, onChange }: { data: Overview; onChange: () => void }) {
  const [status, setStatus] = useState("");
  const list = useApi<OutMsg[]>(`/admin/integrations/outbound?limit=100${status ? `&status=${status}` : ""}`, [status]);
  const [detail, setDetail] = useState<OutMsg | null>(null);
  const o = data.outbound;
  async function run() { await api("/admin/integrations/outbound/deliver", { method: "POST" }); list.reload(); onChange(); }
  async function retry(m: OutMsg) { await api(`/admin/integrations/outbound/${m.id}/retry`, { method: "POST" }); list.reload(); onChange(); }
  async function open(m: OutMsg) { setDetail(await api<OutMsg>(`/admin/integrations/outbound/${m.id}`)); }
  return (
    <Stack gap={2}>
      <Alert severity={o.mode === "HTTP" ? "success" : "info"}>
        {o.mode === "HTTP"
          ? <>Delivering to the EHR FHIR endpoint (<code>OUTBOUND_FHIR_URL</code>). Failed deliveries retry with backoff, up to {o.max_attempts} attempts.</>
          : <>No EHR endpoint is configured, so delivery is <strong>simulated</strong>: resources are built and logged but not sent. Set <code>OUTBOUND_FHIR_URL</code> (and <code>OUTBOUND_FHIR_TOKEN</code>) to deliver for real.</>}
      </Alert>
      <Stack direction={{ xs: "column", sm: "row" }} gap={1} alignItems={{ sm: "center" }} justifyContent="space-between">
        <Stack direction="row" gap={1} flexWrap="wrap">
          {["SENT", "PENDING", "FAILED"].map((k) => <Chip key={k} label={`${k.toLowerCase()}: ${o.counts[k] ?? 0}`} color={OUT_COLOR[k]} variant="outlined" size="small" />)}
        </Stack>
        <Stack direction="row" gap={1}>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel id="out-status">Status</InputLabel>
            <Select labelId="out-status" label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <MenuItem value="">All</MenuItem>{["SENT", "PENDING", "FAILED"].map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
            </Select>
          </FormControl>
          <Button variant="outlined" startIcon={<PlayArrowRounded />} onClick={run}>Deliver now</Button>
        </Stack>
      </Stack>
      {list.loading && !list.data ? <Loading /> : (
        <TableContainer component={Card}>
          <Table size="small">
            <TableHead><TableRow>{["Queued", "Resource", "Patient", "Status", "Attempts", "Delivered", ""].map((h) => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {(list.data ?? []).length === 0 && <TableRow><TableCell colSpan={7}>Nothing queued yet. RED/AMBER alerts and completed surveys appear here.</TableCell></TableRow>}
              {(list.data ?? []).map((m) => (
                <TableRow key={m.id} hover sx={{ cursor: "pointer" }} onClick={() => open(m)}>
                  <TableCell>{fmtDateTime(m.created_at)}</TableCell>
                  <TableCell>{m.resource_type}<Typography variant="caption" display="block" color="text.secondary">{m.related_type}</Typography></TableCell>
                  <TableCell>{m.patient_mrn ?? "—"}</TableCell>
                  <TableCell><Chip size="small" label={m.status} color={OUT_COLOR[m.status]} />{m.delivery_mode === "SIMULATED" && <Chip size="small" variant="outlined" label="simulated" sx={{ ml: 0.5 }} />}</TableCell>
                  <TableCell>{m.attempts}{m.last_error && <Typography variant="caption" display="block" color="error">{m.last_error}</Typography>}</TableCell>
                  <TableCell>{m.sent_at ? timeAgo(m.sent_at) : "—"}</TableCell>
                  <TableCell>{m.status !== "SENT" && <Button size="small" onClick={(e) => { e.stopPropagation(); retry(m); }}>Retry</Button>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      <Dialog open={!!detail} onClose={() => setDetail(null)} fullWidth maxWidth="md">
        <DialogTitle>{detail?.resource_type} → {detail?.destination}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" mb={1}>Payload contains PHI; opening it is recorded in the audit trail.</Typography>
          {detail?.payload && <Mono maxHeight={480}>{JSON.stringify(JSON.parse(detail.payload), null, 2)}</Mono>}
        </DialogContent>
        <DialogActions><Button onClick={() => setDetail(null)}>Close</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}
