import LockRounded from "@mui/icons-material/LockRounded";
import {
  Alert, Box, Card, CardContent, Chip, Grid, LinearProgress, List, ListItem, ListItemText, Stack, Tab, Tabs, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useApi } from "../../api/client";
import type { Phase } from "../../api/types";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader, Section, titleCase } from "../../components/common";

interface Link { patient_id: string; first_name: string; relationship: string; status: string; scopes: string[] }
interface View {
  patient_first_name: string; relationship: string; granted_scopes: string[]; notice: string;
  recovery_status?: { phase: Phase; recovery_day: number; care_team_following_up: boolean; message: string };
  progress?: { recovery_day: number; progress_pct: number; checked_in_today: boolean };
  tasks?: { title: string; category: string; completed: boolean }[];
  reminders?: { name: string; time: string; status: string }[];
  appointments?: { type: string; scheduled_at: string; location: string }[];
}

export default function CaregiverHome() {
  const links = useApi<Link[]>("/caregiver/patients");
  const active = (links.data ?? []).filter((l) => l.status === "ACTIVE");
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { if (!sel && active.length) setSel(active[0].patient_id); }, [active, sel]);
  const view = useApi<View>(sel ? `/caregiver/patients/${sel}` : null, [sel]);

  if (links.loading) return <Loading />;
  if (links.error) return <ErrorState message={links.error} />;
  const revoked = (links.data ?? []).filter((l) => l.status !== "ACTIVE");

  return (
    <Stack gap={2.5} maxWidth={900} mx="auto">
      <PageHeader title="Shared recovery" subtitle="Information patients have chosen to share with you." />
      {active.length === 0 && <Alert severity="info">No one is currently sharing recovery information with you.</Alert>}
      {active.length > 1 && (
        <Tabs value={sel} onChange={(_, v) => setSel(v)} variant="scrollable">
          {active.map((l) => <Tab key={l.patient_id} value={l.patient_id} label={`${l.first_name} (${l.relationship})`} />)}
        </Tabs>
      )}
      {view.loading && sel && <Loading />}
      {view.error && <ErrorState message={view.error} />}
      {view.data && <CaregiverView v={view.data} />}
      {revoked.map((l) => (
        <Alert key={l.patient_id} severity="warning" icon={<LockRounded />}>
          {l.first_name} has revoked your access. You can no longer see their recovery information.
        </Alert>
      ))}
    </Stack>
  );
}

function CaregiverView({ v }: { v: View }) {
  return (
    <Stack gap={2.5}>
      <Alert severity="info" icon={<LockRounded />}>{v.notice} Shared: {v.granted_scopes.map(titleCase).join(", ")}.</Alert>
      <Grid container spacing={2.5}>
        {v.recovery_status && (
          <Grid item xs={12} md={6}>
            <Section title={`${v.patient_first_name}'s recovery status`} id="status">
              <Typography variant="subtitle1">{v.recovery_status.phase.label} phase · day {v.recovery_status.recovery_day}</Typography>
              <Typography color="text.secondary">{v.recovery_status.phase.description}</Typography>
              <Chip sx={{ mt: 1.5 }} color={v.recovery_status.care_team_following_up ? "warning" : "success"} variant="outlined" label={v.recovery_status.message} />
            </Section>
          </Grid>
        )}
        {v.progress && (
          <Grid item xs={12} md={6}>
            <Section title="Progress" id="progress">
              <Typography mb={1}>Day {v.progress.recovery_day} of 30</Typography>
              <LinearProgress variant="determinate" value={v.progress.progress_pct} sx={{ height: 10, borderRadius: 5 }} aria-label="Progress" />
              <Typography mt={1.5}>{v.progress.checked_in_today ? "✔ Checked in today" : "Not checked in yet today"}</Typography>
            </Section>
          </Grid>
        )}
        {v.tasks && (
          <Grid item xs={12} md={6}>
            <Section title="Today's tasks" id="tasks">
              <List dense>{v.tasks.map((t) => <ListItem key={t.title} disableGutters><ListItemText primary={`${t.completed ? "✔" : "○"} ${t.title}`} /></ListItem>)}</List>
            </Section>
          </Grid>
        )}
        {v.reminders && (
          <Grid item xs={12} md={6}>
            <Section title="Reminders" id="reminders">
              {v.reminders.length === 0 ? <EmptyState text="No reminders today." /> : v.reminders.map((r, i) => (
                <Stack key={i} direction="row" justifyContent="space-between"><Typography>{r.time} · {r.name}</Typography><Chip size="small" label={titleCase(r.status)} /></Stack>
              ))}
            </Section>
          </Grid>
        )}
        {v.appointments && (
          <Grid item xs={12} md={6}>
            <Section title="Upcoming appointments" id="appts">
              {v.appointments.map((a, i) => <Box key={i}><Typography>{fmtDateTime(a.scheduled_at)} · {titleCase(a.type)}</Typography><Typography variant="body2" color="text.secondary">{a.location}</Typography></Box>)}
            </Section>
          </Grid>
        )}
      </Grid>
      <Card variant="outlined"><CardContent>
        <Typography variant="body2" color="text.secondary">
          Not shared with caregivers: clinical notes, check-in answers, care-team messages, medication doses and medical history.
        </Typography>
      </CardContent></Card>
    </Stack>
  );
}
