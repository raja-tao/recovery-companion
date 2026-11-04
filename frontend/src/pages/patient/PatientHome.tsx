import AssignmentRounded from "@mui/icons-material/AssignmentRounded";
import ChatRounded from "@mui/icons-material/ChatRounded";
import CheckCircleRounded from "@mui/icons-material/CheckCircleRounded";
import EventRounded from "@mui/icons-material/EventRounded";
import FactCheckRounded from "@mui/icons-material/FactCheckRounded";
import MedicationRounded from "@mui/icons-material/MedicationRounded";
import QuestionAnswerRounded from "@mui/icons-material/QuestionAnswerRounded";
import RadioButtonUncheckedRounded from "@mui/icons-material/RadioButtonUncheckedRounded";
import RouteRounded from "@mui/icons-material/RouteRounded";
import TaskAltRounded from "@mui/icons-material/TaskAltRounded";
import FavoriteRounded from "@mui/icons-material/FavoriteRounded";
import {
  Alert, AlertTitle, Box, Button, Checkbox, Chip, Grid, LinearProgress, List, ListItem, ListItemButton, ListItemIcon,
  ListItemText, Stack, Step, StepLabel, Stepper, Typography,
} from "@mui/material";
import { useEffect } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { Dashboard } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorState, fmtDate, fmtDateTime, Loading, Section, SeverityChip, timeAgo, titleCase } from "../../components/common";

export default function PatientHome() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<Dashboard>(`/patients/${user!.patient_id}/dashboard`);
  useEffect(() => {
    window.addEventListener("rc:mood", reload);
    return () => window.removeEventListener("rc:mood", reload);
  }, [reload]);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} onRetry={reload} />;

  const d = data;
  const phaseIndex = d.phases.findIndex((p) => p.key === d.phase.key);
  const done = d.tasks.filter((t) => t.completed).length;

  async function toggle(taskId: string) {
    await api(`/patients/${user!.patient_id}/tasks/${taskId}/complete`, { method: "POST" });
    reload();
  }

  return (
    <Stack gap={2.5}>
      <Box>
        <Typography variant="h4" component="h1">Hi {d.patient.first_name}</Typography>
        <Typography color="text.secondary">
          {d.episode?.procedure_name} · Day {d.recovery_day} of 30 · {fmtDate(new Date().toISOString())}
        </Typography>
      </Box>

      {d.escalation_status && (
        <Alert severity={d.escalation_status.severity === "RED" ? "error" : "warning"} variant="outlined" role="status">
          <AlertTitle>Your care team is following up</AlertTitle>
          {d.escalation_status.message} <Typography component="span" variant="caption">({timeAgo(d.escalation_status.since)})</Typography>
          {d.escalation_status.severity === "RED" && (
            <Typography variant="body2" mt={0.5} fontWeight={600}>If you feel worse, or have chest pain or trouble breathing, call 911.</Typography>
          )}
        </Alert>
      )}

      {d.surveys_due.map((s) => (
        <Alert key={s.timepoint} severity="info" icon={<AssignmentRounded />}
          action={<Button component={RouterLink} to="/patient/surveys" color="inherit" size="small">Start</Button>}>
          <strong>{s.title}</strong> is ready ({s.label}). It takes about 2 minutes.
        </Alert>
      ))}

      {/* Recovery status */}
      <Section title="Today's recovery status" icon={<RouteRounded color="primary" />} id="status"
        action={<SeverityChip level={d.current_risk} long />}>
        <Typography variant="subtitle1">{d.phase.label} phase</Typography>
        <Typography color="text.secondary" mb={2}>{d.phase.description}</Typography>
        <Stepper activeStep={phaseIndex} alternativeLabel sx={{ mb: 2, display: { xs: "none", sm: "flex" } }}>
          {d.phases.map((p) => (
            <Step key={p.key}><StepLabel optional={<Typography variant="caption">Days {p.start_day}–{p.end_day}</Typography>}>{p.label}</StepLabel></Step>
          ))}
        </Stepper>
        <Stack direction="row" justifyContent="space-between" mb={0.5}>
          <Typography variant="body2">Recovery progress</Typography>
          <Typography variant="body2" fontWeight={600}>Day {d.recovery_day} / 30</Typography>
        </Stack>
        <LinearProgress variant="determinate" value={d.progress_pct} sx={{ height: 10, borderRadius: 5 }} aria-label="Recovery progress" />
        {!d.plan_approved && (
          <Alert severity="info" sx={{ mt: 2 }}>Your recovery plan is waiting for your surgeon's approval. Follow your printed discharge instructions until then.</Alert>
        )}
      </Section>

      <Grid container spacing={2.5}>
        <Grid item xs={12} md={6}>
          <Section title="Daily check-in" icon={<FactCheckRounded color="primary" />} id="checkin">
            {d.checkin.completed_today ? (
              <Stack direction="row" alignItems="center" gap={1.5}>
                <CheckCircleRounded color="success" />
                <Box flex={1}>
                  <Typography fontWeight={600}>Done for today</Typography>
                  <Typography variant="body2" color="text.secondary">Submitted {timeAgo(d.checkin.submitted_at)}</Typography>
                </Box>
                <SeverityChip level={d.checkin.risk_level} />
              </Stack>
            ) : (
              <Stack gap={1.5}>
                <Typography>Your 2-minute check-in helps your care team spot problems early.</Typography>
                <Button component={RouterLink} to="/patient/checkin" variant="contained" size="large" startIcon={<FactCheckRounded />}>
                  Start today's check-in
                </Button>
              </Stack>
            )}
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Ask the recovery assistant" icon={<QuestionAnswerRounded color="primary" />} id="ask">
            <Typography mb={1.5}>Questions about your approved instructions — driving, showering, exercises and more.</Typography>
            <Stack direction="row" gap={1} flexWrap="wrap" mb={1.5}>
              {["When can I drive?", "Can I shower?", "What exercises are in my plan?"].map((q) => (
                <Chip key={q} label={q} component={RouterLink} to={`/patient/assistant?q=${encodeURIComponent(q)}`} clickable variant="outlined" />
              ))}
            </Stack>
            <Button component={RouterLink} to="/patient/assistant" variant="outlined">Open assistant</Button>
          </Section>
        </Grid>

        <Grid item xs={12} md={6}>
          <Section title="Today's tasks" icon={<TaskAltRounded color="primary" />} id="tasks"
            action={<Chip size="small" label={`${done}/${d.tasks.length} done`} />}>
            {d.tasks.length === 0 ? <EmptyState text="No tasks for today." /> : (
              <List dense disablePadding>
                {d.tasks.map((t) => (
                  <ListItem key={t.id} disablePadding>
                    <ListItemButton onClick={() => toggle(t.id)} role="checkbox" aria-checked={t.completed}>
                      <ListItemIcon sx={{ minWidth: 40 }}>
                        <Checkbox edge="start" checked={t.completed} tabIndex={-1} disableRipple
                          icon={<RadioButtonUncheckedRounded />} checkedIcon={<CheckCircleRounded />} inputProps={{ "aria-label": t.title }} />
                      </ListItemIcon>
                      <ListItemText primary={t.title} secondary={t.detail}
                        primaryTypographyProps={{ sx: { textDecoration: t.completed ? "line-through" : undefined, fontWeight: 600 } }} />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            )}
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Medications today" icon={<MedicationRounded color="primary" />} id="meds"
            action={<Button component={RouterLink} to="/patient/medications" size="small">All medications</Button>}>
            <List dense disablePadding>
              {d.medications.map((m, i) => (
                <ListItem key={i} disableGutters secondaryAction={<MedStatus status={m.status} />}>
                  <ListItemText primary={`${m.time} · ${m.name}`} secondary={m.dose_text} />
                </ListItem>
              ))}
            </List>
          </Section>
        </Grid>

        <Grid item xs={12} md={6}>
          <Section title="Upcoming appointment" icon={<EventRounded color="primary" />} id="appt"
            action={<Button component={RouterLink} to="/patient/appointments" size="small">All</Button>}>
            {d.next_appointment ? (
              <Box>
                <Typography fontWeight={600}>{titleCase(d.next_appointment.appointment_type)}</Typography>
                <Typography>{fmtDateTime(d.next_appointment.scheduled_at)}</Typography>
                <Typography color="text.secondary">{d.next_appointment.provider_name} · {d.next_appointment.location}</Typography>
                {d.next_appointment.transportation_status === "UNKNOWN" && (
                  <Button component={RouterLink} to="/patient/appointments" size="small" variant="outlined" sx={{ mt: 1 }}>How will you get there? Request a pickup</Button>
                )}
                {d.next_appointment.transport?.status === "SCHEDULED" && (
                  <Chip sx={{ mt: 1 }} color="info" variant="outlined" label={`Ride booked · pickup ${fmtDateTime(d.next_appointment.transport.pickup_at)}`} />
                )}
                {d.next_appointment.transport?.status === "REQUESTED" && (
                  <Chip sx={{ mt: 1 }} color="warning" variant="outlined" label="Ride requested · coordinator will confirm" />
                )}
              </Box>
            ) : <EmptyState text="No upcoming appointments." />}
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="How you've been feeling" icon={<FavoriteRounded color="primary" />} id="mood">
            {d.mood.length === 0 ? <EmptyState text="We'll ask how you're feeling each time you sign in." /> : (
              <Stack direction="row" gap={1.5} flexWrap="wrap" role="list" aria-label="Mood over the last 7 days">
                {d.mood.map((m) => (
                  <Stack key={m.date} alignItems="center" role="listitem" aria-label={`${fmtDate(m.date)}: ${titleCase(m.mood)}`}>
                    <Box sx={{ fontSize: 28, lineHeight: 1 }} aria-hidden>{MOOD_EMOJI[m.mood]}</Box>
                    <Typography variant="caption" color="text.secondary">{new Date(m.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" })}</Typography>
                  </Stack>
                ))}
              </Stack>
            )}
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Messages from your care team" icon={<ChatRounded color="primary" />} id="msgs"
            action={<Button component={RouterLink} to="/patient/messages" size="small">
              Open{d.unread_messages ? ` (${d.unread_messages} new)` : ""}</Button>}>
            {d.care_team_messages.length === 0 ? <EmptyState text="No messages yet." /> :
              d.care_team_messages.slice(0, 2).map((m) => (
                <Box key={m.id} mb={1}>
                  <Typography variant="body2" fontWeight={600}>{m.sender_name} · {timeAgo(m.created_at)}</Typography>
                  <Typography variant="body2">{m.content}</Typography>
                </Box>
              ))}
          </Section>
        </Grid>
      </Grid>
    </Stack>
  );
}

const MOOD_EMOJI: Record<string, string> = { GREAT: "😄", GOOD: "🙂", OKAY: "😐", LOW: "😟", BAD: "😣" };

export function MedStatus({ status }: { status: string }) {
  const map: Record<string, { color: "success" | "warning" | "error" | "default" | "info"; label: string }> = {
    TAKEN: { color: "success", label: "Taken" }, MISSED: { color: "error", label: "Missed" },
    SKIPPED: { color: "warning", label: "Skipped" }, UNKNOWN: { color: "default", label: "Unknown" },
    DUE: { color: "info", label: "Due now" }, OVERDUE: { color: "warning", label: "Not recorded" },
    UPCOMING: { color: "default", label: "Upcoming" }, AS_NEEDED: { color: "default", label: "As needed" },
  };
  const m = map[status] ?? { color: "success" as const, label: status.replace("TAKEN", "Taken") };
  return <Chip size="small" color={m.color} variant={m.color === "default" ? "outlined" : "filled"} label={m.label} />;
}
