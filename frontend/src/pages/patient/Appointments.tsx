import AirportShuttleRounded from "@mui/icons-material/AirportShuttleRounded";
import DirectionsCarRounded from "@mui/icons-material/DirectionsCarRounded";
import EventRounded from "@mui/icons-material/EventRounded";
import SupportAgentRounded from "@mui/icons-material/SupportAgentRounded";
import {
  Alert, Box, Button, Card, CardContent, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, FormGroup, Stack, TextField, Typography, useMediaQuery, useTheme,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import type { Appointment, TransportRequest } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader, titleCase } from "../../components/common";

const MOBILITY = [
  { key: "WALKER", label: "I use a walker" }, { key: "CANE", label: "I use a cane" },
  { key: "WHEELCHAIR", label: "I need a wheelchair-accessible vehicle" }, { key: "STEP_HELP", label: "I need help with steps" },
];

const RIDE_CHIP: Record<string, { label: string; color: "default" | "success" | "warning" | "info" }> = {
  UNKNOWN: { label: "Ride: not confirmed", color: "default" }, CONFIRMED: { label: "Ride: own ride", color: "success" },
  NEEDS_HELP: { label: "Ride: requested", color: "warning" }, ARRANGED: { label: "Ride: booked", color: "info" },
};

export default function Appointments() {
  const { user } = useAuth();
  const pid = user!.patient_id;
  const { data, error, loading, reload } = useApi<Appointment[]>(`/patients/${pid}/appointments`);
  const [msg, setMsg] = useState<string | null>(null);
  const [pickupFor, setPickupFor] = useState<Appointment | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} onRetry={reload} />;
  const upcoming = data.filter((a) => a.status === "SCHEDULED" && new Date(a.scheduled_at) > new Date());
  const past = data.filter((a) => !upcoming.includes(a));

  async function ownRide(a: Appointment) {
    const r = await api<{ message: string }>(`/patients/${pid}/appointments/${a.id}/transportation`, { body: { status: "CONFIRMED" } });
    setMsg(r.message);
    reload();
  }
  async function needHelp(a: Appointment) {
    const r = await api<{ message: string }>(`/patients/${pid}/appointments/${a.id}/transport-request`, { body: { kind: "HELP_FINDING_RIDE" } });
    setMsg(r.message);
    reload();
  }
  async function cancelRide(t: TransportRequest) {
    await api(`/patients/${pid}/transport-requests/${t.id}/cancel`, { body: { reason: "I have my own ride now" } });
    setMsg("Ride request cancelled — glad you have a ride.");
    reload();
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Appointments" subtitle="Follow-up visits are an important part of your recovery. We can help you get there." />
      {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}
      <Typography variant="h6" component="h2">Upcoming</Typography>
      {upcoming.length === 0 && <EmptyState text="No upcoming appointments." />}
      {upcoming.map((a) => {
        const chip = RIDE_CHIP[a.transportation_status] ?? RIDE_CHIP.UNKNOWN;
        const t = a.transport;
        return (
          <Card key={a.id}><CardContent>
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={1}>
              <Stack direction="row" gap={1.5}>
                <EventRounded color="primary" />
                <Box>
                  <Typography variant="subtitle1">{titleCase(a.appointment_type)}</Typography>
                  <Typography>{fmtDateTime(a.scheduled_at)}</Typography>
                  <Typography color="text.secondary">{a.provider_name} · {a.location}</Typography>
                </Box>
              </Stack>
              <Chip icon={<DirectionsCarRounded />} variant="outlined" label={chip.label} color={chip.color} sx={{ alignSelf: "flex-start" }} />
            </Stack>

            {a.transportation_status === "UNKNOWN" && (
              <Box mt={2} p={2} sx={{ bgcolor: "#f9fafb", borderRadius: 2 }}>
                <Typography fontWeight={600} mb={1.5}>How will you get to this appointment?</Typography>
                <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
                  <Button variant="contained" startIcon={<DirectionsCarRounded />} onClick={() => ownRide(a)}>I have a ride</Button>
                  <Button variant="outlined" startIcon={<AirportShuttleRounded />} onClick={() => setPickupFor(a)}>Hospital pickup, please</Button>
                  <Button variant="outlined" color="warning" startIcon={<SupportAgentRounded />} onClick={() => needHelp(a)}>Help me find a ride</Button>
                </Stack>
              </Box>
            )}

            {t?.status === "REQUESTED" && (
              <Alert severity="info" sx={{ mt: 2 }}
                action={<Button color="inherit" size="small" onClick={() => cancelRide(t)}>I have a ride now</Button>}>
                {t.kind === "HOSPITAL_PICKUP" ? "Pickup requested" : "Help requested"} — a care coordinator will book your ride and send you the pickup time.
              </Alert>
            )}
            {t?.status === "SCHEDULED" && (
              <Alert severity="success" icon={<AirportShuttleRounded />} sx={{ mt: 2 }}>
                <Typography fontWeight={700}>Your ride is booked</Typography>
                <Typography variant="body2">{t.mode_label}{t.vendor ? ` · ${t.vendor}` : ""}</Typography>
                <Typography variant="body2">Pickup <strong>{fmtDateTime(t.pickup_at)}</strong>{t.pickup_address ? ` from ${t.pickup_address}` : ""}</Typography>
                {t.vehicle && <Typography variant="body2">Vehicle: {t.vehicle}{t.driver_name ? ` · Driver ${t.driver_name}` : ""}</Typography>}
                {t.confirmation_code && <Typography variant="body2">Confirmation: <strong>{t.confirmation_code}</strong></Typography>}
                {t.contact_phone && <Button size="small" href={`tel:${t.contact_phone}`} sx={{ mt: 0.5, px: 0 }}>Call {t.contact_phone}</Button>}
                <Typography variant="caption" display="block">Please be ready 10 minutes early. {t.return_trip ? "A return ride is included." : ""}</Typography>
              </Alert>
            )}
          </CardContent></Card>
        );
      })}
      {past.length > 0 && <Typography variant="h6" component="h2">Past</Typography>}
      {past.map((a) => (
        <Stack key={a.id} direction="row" justifyContent="space-between" px={1} gap={1}>
          <Typography>{fmtDateTime(a.scheduled_at)} · {titleCase(a.appointment_type)}</Typography>
          <Chip size="small" label={titleCase(a.status)} color={a.status === "COMPLETED" ? "success" : "default"} variant="outlined" />
        </Stack>
      ))}
      {pickupFor && <PickupDialog appt={pickupFor} patientId={pid!} onClose={() => setPickupFor(null)}
        onDone={(m) => { setPickupFor(null); setMsg(m); reload(); }} />}
    </Stack>
  );
}

function PickupDialog({ appt, patientId, onClose, onDone }: { appt: Appointment; patientId: string; onClose: () => void; onDone: (msg: string) => void }) {
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down("sm"));
  const [address, setAddress] = useState("");
  const [needs, setNeeds] = useState<string[]>([]);
  const [returnTrip, setReturnTrip] = useState(true);
  const [companion, setCompanion] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>(`/patients/${patientId}/appointments/${appt.id}/transport-request`, {
        body: { kind: "HOSPITAL_PICKUP", pickup_address: address.trim(), mobility_needs: needs, return_trip: returnTrip,
          companion, note: note.trim() || undefined },
      });
      onDone(r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={onClose} fullScreen={phone} fullWidth maxWidth="sm" aria-labelledby="pickup-title">
      <DialogTitle id="pickup-title">Request a hospital pickup</DialogTitle>
      <DialogContent>
        <Stack gap={2} pt={1}>
          <Typography color="text.secondary">For your {titleCase(appt.appointment_type).toLowerCase()} on {fmtDateTime(appt.scheduled_at)}. A coordinator books the hospital shuttle or a medical transport van and sends you the pickup time.</Typography>
          <TextField label="Pickup address" required value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="street-address"
            inputProps={{ maxLength: 300 }} />
          <Box>
            <Typography variant="subtitle2">Anything the driver should know?</Typography>
            <FormGroup>
              {MOBILITY.map((m) => (
                <FormControlLabel key={m.key} label={m.label} control={<Checkbox checked={needs.includes(m.key)}
                  onChange={(e) => setNeeds(e.target.checked ? [...needs, m.key] : needs.filter((x) => x !== m.key))} />} />
              ))}
              <FormControlLabel label="Someone will come with me" control={<Checkbox checked={companion} onChange={(e) => setCompanion(e.target.checked)} />} />
              <FormControlLabel label="I need a ride home too" control={<Checkbox checked={returnTrip} onChange={(e) => setReturnTrip(e.target.checked)} />} />
            </FormGroup>
          </Box>
          <TextField label="Note for the coordinator (optional)" multiline minRows={2} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. second floor, no elevator" inputProps={{ maxLength: 500 }} />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={busy || !address.trim()}>Request pickup</Button>
      </DialogActions>
    </Dialog>
  );
}
