import AirportShuttleRounded from "@mui/icons-material/AirportShuttleRounded";
import {
  Alert, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid, MenuItem, Stack,
  TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { Appointment, TransportRequest } from "../../api/types";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader, titleCase } from "../../components/common";

type Row = TransportRequest & { patient_id: string; patient_name: string; patient_phone: string | null; mrn: string; appointment: Appointment };
type Options = { modes: { key: string; label: string }[]; mobility_needs: { key: string; label: string }[] };

const STATUS_COLOR: Record<string, "warning" | "info" | "success" | "default"> = { REQUESTED: "warning", SCHEDULED: "info", COMPLETED: "success", CANCELLED: "default" };

/** Local "YYYY-MM-DDTHH:mm" for a datetime-local input. */
function localInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function Transport() {
  const [view, setView] = useState("REQUESTED,SCHEDULED");
  const { data, error, loading, reload } = useApi<Row[]>(`/transport-requests?status=${view}`, [view]);
  const { data: opts } = useApi<Options>("/transport/options");
  const [booking, setBooking] = useState<Row | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const needLabel = (k: string) => opts?.mobility_needs.find((m) => m.key === k)?.label ?? titleCase(k);

  async function act(r: Row, action: "complete" | "cancel") {
    await api(`/transport-requests/${r.id}/${action}`, { body: action === "cancel" ? { reason: "Cancelled by coordinator" } : undefined, method: "POST" });
    setMsg(action === "complete" ? "Ride marked completed." : "Ride cancelled; the patient has been asked again how they'll get there.");
    reload();
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Rides to appointments" subtitle="Hospital pickups and ride help requested by patients. Booking a ride tells the patient the pickup time and resolves the task."
        action={<Button variant="outlined" onClick={reload}>Refresh</Button>} />
      <ToggleButtonGroup exclusive size="small" value={view} onChange={(_, v) => v && setView(v)} aria-label="Filter">
        <ToggleButton value="REQUESTED,SCHEDULED">Open</ToggleButton>
        <ToggleButton value="REQUESTED">To book</ToggleButton>
        <ToggleButton value="SCHEDULED">Booked</ToggleButton>
        <ToggleButton value="COMPLETED,CANCELLED">Closed</ToggleButton>
      </ToggleButtonGroup>
      {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}
      {loading && !data ? <Loading /> : error || !data ? <ErrorState message={error ?? ""} onRetry={reload} /> : data.length === 0 ? <EmptyState text="No ride requests." /> : (
        <Grid container spacing={2}>
          {data.map((r) => (
            <Grid item xs={12} md={6} key={r.id}>
              <Card sx={{ height: "100%" }}><CardContent>
                <Stack direction="row" justifyContent="space-between" gap={1} mb={1}>
                  <Typography fontWeight={700} component={RouterLink} to={`/care-team/patients/${r.patient_id}`} sx={{ color: "inherit" }}>{r.patient_name}</Typography>
                  <Chip size="small" label={titleCase(r.status)} color={STATUS_COLOR[r.status]} />
                </Stack>
                <Typography variant="body2">{titleCase(r.appointment.appointment_type)} · <strong>{fmtDateTime(r.appointment.scheduled_at)}</strong></Typography>
                <Typography variant="body2" color="text.secondary">{r.appointment.location}</Typography>
                <Typography variant="body2" mt={1}><strong>{r.kind === "HOSPITAL_PICKUP" ? "Hospital pickup" : "Help finding a ride"}</strong>
                  {r.pickup_address && <> from {r.pickup_address}</>}{r.return_trip ? " · return trip" : ""}{r.companion ? " · +1 companion" : ""}</Typography>
                {r.mobility_needs.length > 0 && (
                  <Stack direction="row" gap={0.5} flexWrap="wrap" mt={0.5}>{r.mobility_needs.map((m) => <Chip key={m} size="small" variant="outlined" label={needLabel(m)} />)}</Stack>
                )}
                {r.patient_note && <Typography variant="body2" mt={0.5}>“{r.patient_note}”</Typography>}
                {r.status === "SCHEDULED" && (
                  <Alert severity="info" icon={<AirportShuttleRounded />} sx={{ mt: 1 }}>
                    {r.mode_label}{r.vendor ? ` · ${r.vendor}` : ""} · pickup {fmtDateTime(r.pickup_at)}{r.confirmation_code ? ` · ${r.confirmation_code}` : ""}
                  </Alert>
                )}
                <Stack direction="row" gap={1} mt={1.5} flexWrap="wrap">
                  {r.patient_phone && <Button size="small" href={`tel:${r.patient_phone}`}>Call patient</Button>}
                  {["REQUESTED", "SCHEDULED"].includes(r.status) && <Button size="small" variant="contained" onClick={() => setBooking(r)}>{r.status === "SCHEDULED" ? "Change booking" : "Book ride"}</Button>}
                  {r.status === "SCHEDULED" && <Button size="small" onClick={() => act(r, "complete")}>Completed</Button>}
                  {["REQUESTED", "SCHEDULED"].includes(r.status) && <Button size="small" color="warning" onClick={() => act(r, "cancel")}>Cancel</Button>}
                </Stack>
              </CardContent></Card>
            </Grid>
          ))}
        </Grid>
      )}
      {booking && opts && <BookDialog row={booking} modes={opts.modes} onClose={() => setBooking(null)}
        onDone={() => { setBooking(null); setMsg("Ride booked — the patient has been notified."); reload(); }} />}
    </Stack>
  );
}

function BookDialog({ row, modes, onClose, onDone }: { row: Row; modes: { key: string; label: string }[]; onClose: () => void; onDone: () => void }) {
  const appt = new Date(row.appointment.scheduled_at);
  const [form, setForm] = useState({
    mode: row.mode ?? (row.mobility_needs.includes("WHEELCHAIR") ? "NEMT" : "HOSPITAL_SHUTTLE"), vendor: row.vendor ?? "",
    pickup_at: localInput(row.pickup_at ? new Date(row.pickup_at) : new Date(appt.getTime() - 60 * 60 * 1000)),
    vehicle: row.vehicle ?? "", driver_name: row.driver_name ?? "", contact_phone: row.contact_phone ?? "", confirmation_code: row.confirmation_code ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit() {
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || undefined]));
      await api(`/transport-requests/${row.id}/schedule`, { body: { ...body, pickup_at: new Date(form.pickup_at).toISOString() } });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="book-title">
      <DialogTitle id="book-title">Book ride for {row.patient_name}</DialogTitle>
      <DialogContent>
        <Stack gap={2} pt={1}>
          <Typography variant="body2" color="text.secondary">Appointment {fmtDateTime(row.appointment.scheduled_at)} · {row.appointment.location}</Typography>
          <TextField select label="Ride type" value={form.mode} onChange={set("mode")}>
            {modes.map((m) => <MenuItem key={m.key} value={m.key}>{m.label}</MenuItem>)}
          </TextField>
          <TextField label="Vendor / service" value={form.vendor} onChange={set("vendor")} placeholder="e.g. Hospital shuttle desk" />
          <TextField label="Pickup time" type="datetime-local" value={form.pickup_at} onChange={set("pickup_at")} InputLabelProps={{ shrink: true }} />
          <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
            <TextField label="Vehicle" value={form.vehicle} onChange={set("vehicle")} fullWidth />
            <TextField label="Driver" value={form.driver_name} onChange={set("driver_name")} fullWidth />
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
            <TextField label="Contact phone" value={form.contact_phone} onChange={set("contact_phone")} fullWidth />
            <TextField label="Confirmation code" value={form.confirmation_code} onChange={set("confirmation_code")} fullWidth />
          </Stack>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit}>Book and notify patient</Button>
      </DialogActions>
    </Dialog>
  );
}
