import VerifiedRounded from "@mui/icons-material/VerifiedRounded";
import {
  Alert, Box, Card, CardContent, Chip, Grid, List, ListItem, ListItemText, Stack, Step, StepContent, StepLabel, Stepper,
  Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useApi } from "../../api/client";
import type { Phase } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDate, fmtDateTime, Loading, PageHeader, Section } from "../../components/common";

interface Plan {
  approved: boolean; message?: string; title: string; version: number; status: string; created_by: string; approved_by: string;
  approved_at: string; procedure_name: string; surgery_date: string; recovery_day: number; phase: Phase; phases: Phase[];
  content: {
    surgeon_instructions: string[]; walking_goals: Record<string, string>; activity_goals: Record<string, string>;
    wound_care: string[]; hydration: string; pt_exercises: string[]; sleeping_position: string; appointment_schedule: string[];
    checkin_schedule: string; medication_schedule: string;
    warning_signs: { call_911: string[]; same_day: string[] };
  };
  tasks: { id: string; day_from: number; day_to: number; category: string; title: string }[];
}

export default function RecoveryPlan() {
  const { user } = useAuth();
  const { data, error, loading } = useApi<Plan>(`/patients/${user!.patient_id}/recovery-plan`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} />;
  if (!data.approved) return <Alert severity="info">{data.message}</Alert>;
  const c = data.content;
  const active = data.phases.findIndex((p) => p.key === data.phase.key);

  return (
    <Stack gap={2.5}>
      <PageHeader title="Your 30-day recovery plan" subtitle={`${data.procedure_name} · surgery ${fmtDate(data.surgery_date)}`} />
      <Card sx={{ bgcolor: "#f0fdfa", borderColor: "#99f6e4" }}><CardContent>
        <Stack direction={{ xs: "column", sm: "row" }} gap={1} alignItems={{ sm: "center" }} justifyContent="space-between">
          <Stack direction="row" gap={1} alignItems="center">
            <VerifiedRounded color="primary" />
            <Typography fontWeight={600}>Approved by {data.approved_by}</Typography>
          </Stack>
          <Stack direction="row" gap={1} flexWrap="wrap">
            <Chip size="small" label={`Version ${data.version}`} />
            <Chip size="small" label={`Status: ${data.status}`} color="success" variant="outlined" />
            <Chip size="small" label={`Approved ${fmtDateTime(data.approved_at)}`} variant="outlined" />
            <Chip size="small" label={`Created by ${data.created_by}`} variant="outlined" />
          </Stack>
        </Stack>
      </CardContent></Card>

      <Grid container spacing={2.5}>
        <Grid item xs={12} md={5}>
          <Section title="Your journey" id="journey">
            <Stepper activeStep={active} orientation="vertical">
              {data.phases.map((p) => (
                <Step key={p.key} expanded>
                  <StepLabel optional={<Typography variant="caption">Days {p.start_day}–{p.end_day}</Typography>}>{p.label}</StepLabel>
                  <StepContent>
                    <Typography variant="body2">{c.activity_goals[p.key]}</Typography>
                    <Typography variant="body2" color="text.secondary" mt={0.5}>🚶 {c.walking_goals[p.key]}</Typography>
                  </StepContent>
                </Step>
              ))}
            </Stepper>
          </Section>
        </Grid>
        <Grid item xs={12} md={7}>
          <Stack gap={2.5}>
            <Section title="Surgeon instructions" id="surgeon">
              <List dense>{c.surgeon_instructions.map((s) => <ListItem key={s} disableGutters><ListItemText primary={`• ${s}`} /></ListItem>)}</List>
            </Section>
            <Alert severity="error" variant="outlined">
              <Typography fontWeight={700}>Call 911</Typography>
              {c.warning_signs.call_911.join(" · ")}
              <Typography fontWeight={700} mt={1}>Contact your care team the same day</Typography>
              {c.warning_signs.same_day.join(" · ")}
            </Alert>
          </Stack>
        </Grid>
        <Grid item xs={12} md={6}><Section title="Wound care" id="wound">{c.wound_care.map((w) => <Typography key={w}>• {w}</Typography>)}</Section></Grid>
        <Grid item xs={12} md={6}><Section title="Exercises / PT" id="pt">{c.pt_exercises.map((w) => <Typography key={w}>• {w}</Typography>)}</Section></Grid>
        <Grid item xs={12} md={6}><Section title="Sleeping position" id="sleep"><Typography>{c.sleeping_position}</Typography></Section></Grid>
        <Grid item xs={12} md={6}><Section title="Hydration" id="hydration"><Typography>{c.hydration}</Typography></Section></Grid>
        <Grid item xs={12} md={6}><Section title="Appointments" id="appts">{c.appointment_schedule.map((w) => <Typography key={w}>• {w}</Typography>)}</Section></Grid>
        <Grid item xs={12} md={6}><Section title="Check-ins & medications" id="sched">
          <Typography>{c.checkin_schedule}</Typography><Typography color="text.secondary" mt={1}>{c.medication_schedule}</Typography>
        </Section></Grid>
      </Grid>

      <Section title="Daily task schedule" id="tasks">
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead><TableRow><TableCell>Days</TableCell><TableCell>Category</TableCell><TableCell>Task</TableCell></TableRow></TableHead>
            <TableBody>
              {data.tasks.map((t) => (
                <TableRow key={t.id} selected={data.recovery_day >= t.day_from && data.recovery_day <= t.day_to}>
                  <TableCell>{t.day_from}–{t.day_to}</TableCell><TableCell>{t.category}</TableCell><TableCell>{t.title}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </Section>
    </Stack>
  );
}
