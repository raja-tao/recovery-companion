import ArrowBackRounded from "@mui/icons-material/ArrowBackRounded";
import PhoneRounded from "@mui/icons-material/PhoneRounded";
import SummarizeRounded from "@mui/icons-material/SummarizeRounded";
import {
  Alert as MuiAlert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControl, Grid, InputLabel, MenuItem, Select, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs,
  TextField, Typography,
} from "@mui/material";
import { useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { Alert, Appointment, PatientSummary, SurveyState, TimelineEvent } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  EmptyState, ErrorState, fmtDate, fmtDateTime, Loading, Section, SeverityChip, SlaChip, titleCase,
} from "../../components/common";
import { MessageThread } from "../patient/Messages";
import { MedStatus } from "../patient/PatientHome";

interface AlertDetail extends Alert {
  actions: { action_type: string; contact_method: string | null; outcome: string | null; note: string | null; actor: string | null; created_at: string }[];
  escalations: { id: string; to_role: string; reason: string; status: string; response_note: string | null; created_at: string }[];
}

export default function PatientDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const { user } = useAuth();
  const perms = new Set(user!.permissions);
  const patient = useApi<PatientSummary>(`/patients/${id}`);
  const summary = useApi<{ bullets: string[] }>(`/patients/${id}/summary`);
  const alerts = useApi<Alert[]>(`/patients/${id}/alerts`);
  const [tab, setTab] = useState("alerts");
  const [selected, setSelected] = useState<string | null>(params.get("alert"));

  if (patient.loading) return <Loading />;
  if (patient.error || !patient.data) return <ErrorState message={patient.error ?? "Not found"} />;
  const p = patient.data;
  const refresh = () => { patient.reload(); alerts.reload(); summary.reload(); };

  const tabs = [
    { key: "alerts", label: "Alerts", show: perms.has("alert:read") },
    { key: "timeline", label: "Timeline", show: perms.has("patient:timeline") },
    { key: "checkins", label: "Check-ins", show: perms.has("checkin:read") },
    { key: "wellbeing", label: "Wellbeing", show: perms.has("checkin:read") },
    { key: "meds", label: "Medications", show: perms.has("medication:read") },
    { key: "appts", label: "Appointments", show: perms.has("appointment:read") },
    { key: "notes", label: "Notes", show: perms.has("note:read") },
    { key: "messages", label: "Messages", show: perms.has("message:patient") },
  ].filter((t) => t.show);
  const openAlerts = (alerts.data ?? []).filter((a) => !["RESOLVED", "CLOSED"].includes(a.status));
  const sel = selected ?? openAlerts[0]?.id ?? null;

  return (
    <Stack gap={2.5}>
      <Button component={RouterLink} to="/care-team" startIcon={<ArrowBackRounded />} sx={{ alignSelf: "flex-start" }}>Worklist</Button>
      <Card><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
          <Box>
            <Stack direction="row" gap={1.5} alignItems="center" flexWrap="wrap">
              <Typography variant="h4" component="h1">{p.full_name}</Typography>
              <SeverityChip level={p.current_risk} long size="medium" />
            </Stack>
            <Typography color="text.secondary" mt={0.5}>
              {p.mrn} · DOB {fmtDate(p.date_of_birth)} · {p.phone} · <Chip size="small" label="Synthetic" />
            </Typography>
            {p.episode && (
              <Typography mt={0.5}>
                {p.episode.procedure_name} · surgery {fmtDate(p.episode.surgery_date)} · <strong>day {p.episode.recovery_day}</strong> ({p.episode.phase.label}) · {p.episode.surgeon}
              </Typography>
            )}
          </Box>
          <Button variant="outlined" startIcon={<PhoneRounded />} href={`tel:${p.phone}`} sx={{ alignSelf: "flex-start" }}>Call patient</Button>
        </Stack>
      </CardContent></Card>

      {summary.data && (
        <Section title="Care-team summary" icon={<SummarizeRounded color="primary" />} id="summary"
          action={<Chip size="small" variant="outlined" label="Deterministic · from structured data" />}>
          {summary.data.bullets.map((b) => <Typography key={b} variant="body2" mb={0.5}>• {b}</Typography>)}
        </Section>
      )}

      <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" aria-label="Patient record sections">
          {tabs.map((t) => <Tab key={t.key} value={t.key} label={t.key === "alerts" ? `Alerts (${openAlerts.length} open)` : t.label} />)}
        </Tabs>
      </Box>

      {tab === "alerts" && (
        <Grid container spacing={2.5}>
          <Grid item xs={12} md={5}>
            <Stack gap={1}>
              {(alerts.data ?? []).length === 0 && <EmptyState text="No alerts." />}
              {(alerts.data ?? []).map((a) => (
                <Card key={a.id} sx={{ cursor: "pointer", borderColor: sel === a.id ? "primary.main" : undefined, borderWidth: sel === a.id ? 2 : 1 }}
                  onClick={() => setSelected(a.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(a.id)}>
                  <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
                    <Stack direction="row" justifyContent="space-between" gap={1}>
                      <SeverityChip level={a.severity} />
                      <Chip size="small" label={titleCase(a.status)} />
                    </Stack>
                    <Typography fontWeight={600} mt={1}>{a.trigger}</Typography>
                    <Typography variant="caption" color="text.secondary">{a.rule_id} · {fmtDateTime(a.created_at)}</Typography>
                  </CardContent>
                </Card>
              ))}
            </Stack>
          </Grid>
          <Grid item xs={12} md={7}>
            {sel ? <AlertPanel alertId={sel} onChange={refresh} /> : <EmptyState text="Select an alert." />}
          </Grid>
        </Grid>
      )}
      {tab === "timeline" && <Timeline patientId={id!} />}
      {tab === "checkins" && <Checkins patientId={id!} />}
      {tab === "wellbeing" && <Wellbeing patientId={id!} />}
      {tab === "meds" && <Meds patientId={id!} canApprove={perms.has("medication:guidance")} />}
      {tab === "appts" && <Appts patientId={id!} />}
      {tab === "notes" && <Notes patientId={id!} canWrite={perms.has("note:write")} />}
      {tab === "messages" && <MessageThread patientId={id!} staff />}
    </Stack>
  );
}

function AlertPanel({ alertId, onChange }: { alertId: string; onChange: () => void }) {
  const { user } = useAuth();
  const { data: a, error, loading, reload } = useApi<AlertDetail>(`/alerts/${alertId}`, [alertId]);
  const [dlg, setDlg] = useState<null | "contact" | "escalate" | "resolve">(null);
  const [form, setForm] = useState({ method: "PHONE", outcome: "REACHED", note: "", reason: "", resolution: "" });
  const [err, setErr] = useState<string | null>(null);
  if (loading && !a) return <Loading />;
  if (error || !a) return <ErrorState message={error ?? "Unavailable"} />;
  const canWork = user!.permissions.includes("alert:work");
  const closed = ["RESOLVED", "CLOSED"].includes(a.status);

  async function act(path: string, body: unknown = {}) {
    setErr(null);
    try {
      await api(`/alerts/${a!.id}/${path}`, { body });
      setDlg(null);
      reload();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Card><CardContent>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1} flexWrap="wrap">
        <Box>
          <Stack direction="row" gap={1} alignItems="center"><SeverityChip level={a.severity} long /><Chip size="small" label={titleCase(a.status)} /></Stack>
          <Typography variant="h6" mt={1}>{a.trigger}</Typography>
        </Box>
        <SlaChip sla={a.sla} />
      </Stack>
      <Grid container spacing={1} mt={1}>
        {[
          ["Rule", a.rule_id], ["Category", titleCase(a.category)], ["Source", titleCase(a.source)],
          ["Assigned team", titleCase(a.assigned_team)], ["Created", fmtDateTime(a.created_at)],
          ["Respond within", `${a.required_response_minutes} min (due ${fmtDateTime(a.due_at)})`],
          ["Acknowledged", fmtDateTime(a.acknowledged_at)], ["First contact", fmtDateTime(a.first_contact_at)],
        ].map(([k, v]) => (
          <Grid item xs={6} key={k}><Typography variant="caption" color="text.secondary">{k}</Typography><Typography variant="body2">{v}</Typography></Grid>
        ))}
      </Grid>
      <Typography variant="subtitle2" mt={2}>Evidence (why this alert fired)</Typography>
      <Evidence evidence={a.evidence} />
      {a.resolution && <MuiAlert severity="success" sx={{ mt: 2 }}>Resolution: {a.resolution}</MuiAlert>}
      {err && <MuiAlert severity="error" sx={{ mt: 2 }}>{err}</MuiAlert>}
      {canWork && !closed && (
        <Stack direction="row" gap={1} mt={2} flexWrap="wrap">
          {a.status === "NEW" && <Button variant="contained" onClick={() => act("acknowledge")}>Acknowledge</Button>}
          <Button variant="outlined" startIcon={<PhoneRounded />} onClick={() => setDlg("contact")}>Record outreach</Button>
          {user!.role !== "SURGEON" && <Button variant="outlined" color="warning" onClick={() => setDlg("escalate")}>Escalate to surgeon</Button>}
          <Button variant="outlined" color="success" onClick={() => setDlg("resolve")}>Resolve</Button>
        </Stack>
      )}
      {canWork && a.status === "RESOLVED" && <Button sx={{ mt: 2 }} variant="outlined" onClick={() => act("close")}>Close</Button>}

      <Divider sx={{ my: 2 }} />
      <Typography variant="subtitle2" mb={1}>Activity</Typography>
      {a.actions.length === 0 && <EmptyState text="No actions yet." />}
      {a.actions.map((x, i) => (
        <Box key={i} mb={1}>
          <Typography variant="body2"><strong>{titleCase(x.action_type)}</strong>{x.contact_method ? ` · ${x.contact_method}` : ""}{x.outcome ? ` · ${titleCase(x.outcome)}` : ""} — {x.actor} · {fmtDateTime(x.created_at)}</Typography>
          {x.note && <Typography variant="body2" color="text.secondary">{x.note}</Typography>}
        </Box>
      ))}
      {a.escalations.map((e) => (
        <MuiAlert key={e.id} severity="info" sx={{ mt: 1 }}>
          Escalated to {titleCase(e.to_role)}: {e.reason} — <strong>{titleCase(e.status)}</strong>{e.response_note ? ` · Response: ${e.response_note}` : ""}
        </MuiAlert>
      ))}

      <Dialog open={dlg === "contact"} onClose={() => setDlg(null)} fullWidth maxWidth="sm">
        <DialogTitle>Record outreach</DialogTitle>
        <DialogContent>
          <Stack gap={2} mt={1}>
            <FormControl fullWidth><InputLabel>Method</InputLabel>
              <Select label="Method" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
                {["PHONE", "SMS", "VIDEO", "IN_APP"].map((m) => <MenuItem key={m} value={m}>{titleCase(m)}</MenuItem>)}
              </Select></FormControl>
            <FormControl fullWidth><InputLabel>Outcome</InputLabel>
              <Select label="Outcome" value={form.outcome} onChange={(e) => setForm({ ...form, outcome: e.target.value })}>
                {["REACHED", "NO_ANSWER", "LEFT_VOICEMAIL", "WRONG_NUMBER"].map((m) => <MenuItem key={m} value={m}>{titleCase(m)}</MenuItem>)}
              </Select></FormControl>
            <TextField label="Note" multiline minRows={3} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setDlg(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => act("contact", { method: form.method, outcome: form.outcome, note: form.note || null })}>Save</Button></DialogActions>
      </Dialog>
      <Dialog open={dlg === "escalate"} onClose={() => setDlg(null)} fullWidth maxWidth="sm">
        <DialogTitle>Escalate to surgeon</DialogTitle>
        <DialogContent><TextField sx={{ mt: 1 }} label="Reason" fullWidth multiline minRows={3} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></DialogContent>
        <DialogActions><Button onClick={() => setDlg(null)}>Cancel</Button>
          <Button variant="contained" color="warning" disabled={form.reason.length < 3} onClick={() => act("escalate", { to_role: "SURGEON", reason: form.reason })}>Escalate</Button></DialogActions>
      </Dialog>
      <Dialog open={dlg === "resolve"} onClose={() => setDlg(null)} fullWidth maxWidth="sm">
        <DialogTitle>Resolve alert</DialogTitle>
        <DialogContent><TextField sx={{ mt: 1 }} label="Outcome / resolution" fullWidth multiline minRows={3} value={form.resolution} onChange={(e) => setForm({ ...form, resolution: e.target.value })} /></DialogContent>
        <DialogActions><Button onClick={() => setDlg(null)}>Cancel</Button>
          <Button variant="contained" color="success" disabled={form.resolution.length < 3} onClick={() => act("resolve", { resolution: form.resolution, outcome: "RESOLVED" })}>Resolve</Button></DialogActions>
      </Dialog>
    </CardContent></Card>
  );
}

type Ev = { fact?: string; op?: string; threshold?: unknown; actual?: unknown; rule_id?: string; name?: string; severity?: string; evidence?: Ev[]; rules?: Ev[] };
function Evidence({ evidence }: { evidence: unknown[] }) {
  const fmt = (v: unknown) => (Array.isArray(v) ? v.join(", ") : typeof v === "object" && v !== null ? JSON.stringify(v) : String(v ?? "—"));
  const row = (e: Ev, i: number) => (
    <Typography key={i} variant="body2" sx={{ fontFamily: "ui-monospace, monospace", fontSize: 13 }}>
      {e.fact}: {fmt(e.actual)}{e.op ? `  (rule: ${e.op}${e.threshold == null ? "" : " " + fmt(e.threshold)})` : ""}
    </Typography>
  );
  return (
    <Box sx={{ bgcolor: "#f9fafb", borderRadius: 2, p: 1.5, mt: 0.5 }}>
      {(evidence as Ev[]).map((e, i) =>
        e.rule_id ? (
          <Box key={i} mb={1}><Typography variant="body2" fontWeight={700}>{e.severity} · {e.rule_id} — {e.name}</Typography>{(e.evidence ?? []).map(row)}</Box>
        ) : e.rules ? (
          <Box key={i} mb={1}><Typography variant="caption" color="text.secondary">Repeat trigger</Typography>{e.rules.map((r, j) => <Typography key={j} variant="body2">{r.rule_id} — {r.name}</Typography>)}</Box>
        ) : row(e, i),
      )}
    </Box>
  );
}

function Timeline({ patientId }: { patientId: string }) {
  const { data, error, loading } = useApi<TimelineEvent[]>(`/patients/${patientId}/timeline`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  return (
    <Card><CardContent>
      {data.map((e, i) => (
        <Stack key={i} direction="row" gap={2} py={1} sx={{ borderBottom: "1px solid #f2f4f7" }}>
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 110 }}>{fmtDateTime(e.timestamp)}</Typography>
          <Chip size="small" label={titleCase(e.type)} variant="outlined" sx={{ minWidth: 120 }} />
          <Box flex={1}>
            <Stack direction="row" gap={1} alignItems="center">{e.severity && ["RED", "AMBER"].includes(e.severity) && <SeverityChip level={e.severity} />}<Typography variant="body2" fontWeight={600}>{e.title}</Typography></Stack>
            {e.detail && <Typography variant="body2" color="text.secondary">{e.detail}</Typography>}
            {e.actor && <Typography variant="caption" color="text.secondary">{e.actor}</Typography>}
          </Box>
        </Stack>
      ))}
    </CardContent></Card>
  );
}

function Checkins({ patientId }: { patientId: string }) {
  const { data, error, loading } = useApi<{ id: string; checkin_date: string; recovery_day: number; status: string; risk_level: string; answers: Record<string, unknown>; concern: string | null; rule_results: { rule_id: string }[] }[]>(`/patients/${patientId}/checkins`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  const v = (x: unknown) => (Array.isArray(x) ? x.join(", ") : x === true ? "Yes" : x === false ? "No" : String(x ?? "—"));
  return (
    <Card sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead><TableRow>
          {["Date", "Day", "Risk", "Pain", "Trend", "Temp °F", "Wound", "Swelling", "Mobility", "Meds", "Symptoms", "Rules / concern"].map((h) => <TableCell key={h}>{h}</TableCell>)}
        </TableRow></TableHead>
        <TableBody>
          {data.map((c) => (
            <TableRow key={c.id}>
              <TableCell>{fmtDate(c.checkin_date)}</TableCell><TableCell>{c.recovery_day}</TableCell>
              <TableCell>{c.status === "MISSED" ? <Chip size="small" label="Missed" color="warning" variant="outlined" /> : <SeverityChip level={c.risk_level as never} />}</TableCell>
              {["pain_score", "pain_trend", "temperature", "wound_appearance", "swelling", "mobility", "medication_adherence", "new_symptoms"].map((k) => (
                <TableCell key={k}>{titleCase(v(c.answers[k]))}</TableCell>
              ))}
              <TableCell sx={{ maxWidth: 260 }}>{c.rule_results.map((r) => r.rule_id).join(", ")}{c.concern && <Typography variant="caption" display="block">“{c.concern}”</Typography>}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function Meds({ patientId, canApprove }: { patientId: string; canApprove: boolean }) {
  const [editing, setEditing] = useState<{ id: string; name: string; text: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<{ medications: { id: string; name: string; dose_text: string; frequency: string; indication: string; missed_dose_guidance: string | null }[]; recent_events: { id: string; name: string; scheduled_for: string; status: string }[]; adherence: { rate: number | null } }>(`/patients/${patientId}/medications`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  return (
    <Grid container spacing={2.5}>
      <Grid item xs={12} md={7}>
        <Section title="Medications" id="medlist" action={data.adherence.rate != null && <Chip label={`Adherence ${Math.round(data.adherence.rate * 100)}%`} />}>
          {data.medications.map((m) => (
            <Box key={m.id} mb={1.5}>
              <Typography fontWeight={600}>{m.name} · {m.dose_text} · {m.frequency}</Typography>
              <Typography variant="body2" color="text.secondary">For {m.indication}. Missed-dose guidance: {m.missed_dose_guidance ?? <em>none approved</em>}</Typography>
              {canApprove && (
                <Button size="small" sx={{ px: 0 }} onClick={() => setEditing({ id: m.id, name: m.name, text: m.missed_dose_guidance ?? "" })}>
                  {m.missed_dose_guidance ? "Change guidance" : "Approve missed-dose guidance"}
                </Button>
              )}
            </Box>
          ))}
          {!canApprove && <Typography variant="caption" color="text.secondary">Only the doctor can approve or change medication guidance.</Typography>}
        </Section>
        <Dialog open={!!editing} onClose={() => setEditing(null)} fullWidth maxWidth="sm">
          <DialogTitle>Missed-dose guidance · {editing?.name}</DialogTitle>
          <DialogContent>
            <Typography variant="body2" color="text.secondary" mb={1.5}>The assistant quotes this text word for word when the patient asks about a missed dose. It is recorded as your treatment decision.</Typography>
            <TextField fullWidth multiline minRows={3} value={editing?.text ?? ""} onChange={(e) => editing && setEditing({ ...editing, text: e.target.value })} inputProps={{ maxLength: 1000 }} />
            {saveError && <MuiAlert severity="error" sx={{ mt: 1 }}>{saveError}</MuiAlert>}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
            <Button variant="contained" disabled={(editing?.text.trim().length ?? 0) < 10} onClick={async () => {
              try {
                await api(`/patients/${patientId}/medications/${editing!.id}/guidance`, { body: { missed_dose_guidance: editing!.text } });
                setEditing(null); setSaveError(null); reload();
              } catch (e) { setSaveError((e as Error).message); }
            }}>Approve</Button>
          </DialogActions>
        </Dialog>
      </Grid>
      <Grid item xs={12} md={5}>
        <Section title="Recent dose events" id="medev">
          {data.recent_events.map((e) => (
            <Stack key={e.id} direction="row" justifyContent="space-between" mb={0.5}><Typography variant="body2">{fmtDateTime(e.scheduled_for)} · {e.name}</Typography><MedStatus status={e.status} /></Stack>
          ))}
        </Section>
      </Grid>
    </Grid>
  );
}

function Appts({ patientId }: { patientId: string }) {
  const { data, error, loading } = useApi<Appointment[]>(`/patients/${patientId}/appointments`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  return (
    <Card><Table size="small">
      <TableHead><TableRow>{["When", "Type", "Provider", "Location", "Status", "Transport"].map((h) => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead>
      <TableBody>{data.map((a) => (
        <TableRow key={a.id}><TableCell>{fmtDateTime(a.scheduled_at)}</TableCell><TableCell>{titleCase(a.appointment_type)}</TableCell>
          <TableCell>{a.provider_name}</TableCell><TableCell>{a.location}</TableCell><TableCell>{titleCase(a.status)}</TableCell>
          <TableCell>{titleCase(a.transportation_status)}{a.transport?.status === "SCHEDULED" ? ` · ${a.transport.mode_label}, pickup ${fmtDateTime(a.transport.pickup_at)}` : ""}{a.transportation_note ? ` — ${a.transportation_note}` : ""}</TableCell></TableRow>
      ))}</TableBody>
    </Table></Card>
  );
}

function Notes({ patientId, canWrite }: { patientId: string; canWrite: boolean }) {
  const { data, error, loading, reload } = useApi<{ id: string; action_type: string; note: string | null; outcome: string | null; contact_method: string | null; actor: string; created_at: string }[]>(`/patients/${patientId}/notes`);
  const [text, setText] = useState("");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  return (
    <Stack gap={2}>
      {canWrite && (
        <Stack direction="row" gap={1}>
          <TextField fullWidth size="small" label="Add internal note (not visible to patient or caregiver)" value={text} onChange={(e) => setText(e.target.value)} />
          <Button variant="contained" disabled={!text.trim()} onClick={async () => { await api(`/patients/${patientId}/notes`, { body: { note: text } }); setText(""); reload(); }}>Add</Button>
        </Stack>
      )}
      <Card><CardContent>
        {data.length === 0 && <EmptyState text="No care-team activity yet." />}
        {data.map((n) => (
          <Box key={n.id} mb={1.5}>
            <Typography variant="body2"><strong>{titleCase(n.action_type)}</strong>{n.contact_method ? ` · ${n.contact_method}` : ""}{n.outcome ? ` · ${titleCase(n.outcome)}` : ""} — {n.actor} · {fmtDateTime(n.created_at)}</Typography>
            {n.note && <Typography variant="body2" color="text.secondary">{n.note}</Typography>}
          </Box>
        ))}
      </CardContent></Card>
    </Stack>
  );
}

type MoodHistory = { entries: { id: string; recorded_at: string; mood: string; label: string; emoji: string; feelings: string[]; note: string | null; alert_id: string | null }[]; average_score: number | null; low_days: number };

function Wellbeing({ patientId }: { patientId: string }) {
  const mood = useApi<MoodHistory>(`/patients/${patientId}/mood?days=30`);
  const surveys = useApi<SurveyState[]>(`/patients/${patientId}/surveys`);
  if (mood.loading) return <Loading />;
  if (mood.error || !mood.data) return <ErrorState message={mood.error ?? ""} />;
  const m = mood.data;
  return (
    <Grid container spacing={2.5}>
      <Grid item xs={12} md={7}>
        <Section title="Mood at sign-in (30 days)" id="mood-history"
          action={<Stack direction="row" gap={1}>
            {m.average_score != null && <Chip size="small" label={`Average ${m.average_score} / 5`} />}
            {m.low_days > 0 && <Chip size="small" color="warning" label={`${m.low_days} low day(s) in 5 days`} />}
          </Stack>}>
          {m.entries.length === 0 ? <EmptyState text="No mood answers yet." /> : m.entries.map((e) => (
            <Stack key={e.id} direction="row" gap={1.5} mb={1.25} alignItems="flex-start">
              <Box sx={{ fontSize: 24, lineHeight: 1.2 }} aria-hidden>{e.emoji}</Box>
              <Box>
                <Typography variant="body2" fontWeight={600}>{e.label} · {fmtDateTime(e.recorded_at)}{e.alert_id && <Chip size="small" color="warning" label="Task created" sx={{ ml: 1 }} />}</Typography>
                {e.feelings.length > 0 && <Typography variant="body2" color="text.secondary">{e.feelings.map(titleCase).join(", ")}</Typography>}
                {e.note && <Typography variant="body2">“{e.note}”</Typography>}
              </Box>
            </Stack>
          ))}
        </Section>
      </Grid>
      <Grid item xs={12} md={5}>
        <Section title="Outcome surveys" id="surveys">
          {(surveys.data ?? []).length === 0 ? <EmptyState text="No outcome survey for this procedure." /> : (surveys.data ?? []).map((s) => (
            <Stack key={s.timepoint} direction="row" justifyContent="space-between" mb={1}>
              <Typography variant="body2">{s.title} · {s.label}</Typography>
              <Chip size="small" label={s.state === "COMPLETED" ? `Raw ${s.raw_score}/${s.max_score}` : titleCase(s.state)}
                color={s.state === "COMPLETED" ? "success" : "default"} variant="outlined" />
            </Stack>
          ))}
          <Typography variant="caption" color="text.secondary">Raw sum, 0 = no problems. Completed surveys are sent to the EHR as FHIR QuestionnaireResponse.</Typography>
        </Section>
      </Grid>
    </Grid>
  );
}
