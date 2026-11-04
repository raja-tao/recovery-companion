import FavoriteRounded from "@mui/icons-material/FavoriteRounded";
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Stack,
  TextField, ToggleButton, ToggleButtonGroup, Typography, useMediaQuery, useTheme,
} from "@mui/material";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, useApi } from "../api/client";
import { moodPrompt, useAuth } from "../auth/AuthContext";

type Options = { moods: { key: string; label: string; emoji: string }[]; feelings: { key: string; label: string }[] };
type Reply = { message: string; level: "GREEN" | "AMBER" | "RED"; actions: string[]; nudges: { label: string; to: string }[] };

/** "How are you feeling today?" — shown once after each patient sign-in. */
export default function MoodPrompt({ onRecorded }: { onRecorded?: () => void }) {
  const { user } = useAuth();
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down("sm"));
  const [open, setOpen] = useState(() => moodPrompt.pending());
  const { data } = useApi<Options>(open ? "/wellbeing/options" : null);
  const [mood, setMood] = useState<string | null>(null);
  const [feelings, setFeelings] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [contact, setContact] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState<Reply | null>(null);

  function close() {
    moodPrompt.clear();
    setOpen(false);
  }

  async function submit() {
    if (!mood) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ reply: Reply }>(`/patients/${user!.patient_id}/mood`, {
        body: { mood, feelings, note: note.trim() || undefined, contact_me: contact },
      });
      moodPrompt.clear();
      setReply(r.reply);
      onRecorded?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const firstName = user?.full_name.split(" ")[0];
  return (
    <Dialog open={open} onClose={reply ? close : undefined} fullScreen={phone} maxWidth="sm" fullWidth aria-labelledby="mood-title">
      <DialogTitle id="mood-title" sx={{ pb: 1 }}>
        <Stack direction="row" gap={1} alignItems="center">
          <FavoriteRounded color="primary" aria-hidden />
          {reply ? "Thank you for sharing" : `How are you feeling today, ${firstName}?`}
        </Stack>
      </DialogTitle>
      <DialogContent>
        {reply ? (
          <Stack gap={2}>
            <Alert severity={reply.level === "RED" ? "error" : reply.level === "AMBER" ? "warning" : "success"} icon={false}
              sx={{ fontSize: 16 }} role="status">{reply.message}</Alert>
            {reply.level === "RED" && (
              <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
                <Button variant="contained" color="error" href="tel:988" size="large">Call or text 988</Button>
                <Button variant="outlined" color="error" href="tel:911" size="large">Call 911</Button>
              </Stack>
            )}
            {reply.nudges.length > 0 && (
              <Stack gap={1}>
                <Typography variant="subtitle2">Next steps</Typography>
                {reply.nudges.map((n) => (
                  <Button key={n.to} component={RouterLink} to={n.to} onClick={close} variant="outlined" sx={{ justifyContent: "flex-start" }}>
                    {n.label}
                  </Button>
                ))}
              </Stack>
            )}
          </Stack>
        ) : (
          <Stack gap={2.5}>
            <Typography color="text.secondary">Your answer helps your care team know how you're really doing — not just your symptoms.</Typography>
            <ToggleButtonGroup exclusive value={mood} onChange={(_, v) => v && setMood(v)} aria-label="Mood"
              sx={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 1, "& .MuiToggleButtonGroup-grouped": { border: 1, borderColor: "divider", borderRadius: "12px !important", m: 0 } }}>
              {(data?.moods ?? []).map((m) => (
                <ToggleButton key={m.key} value={m.key} aria-label={m.label} sx={{ flexDirection: "column", py: 1.5, textTransform: "none" }}>
                  <Box component="span" sx={{ fontSize: { xs: 30, sm: 36 }, lineHeight: 1 }} aria-hidden>{m.emoji}</Box>
                  <Typography variant="caption" mt={0.5}>{m.label}</Typography>
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
            <Box>
              <Typography variant="subtitle2" mb={1}>Anything else? <Typography component="span" variant="caption" color="text.secondary">(optional)</Typography></Typography>
              <Stack direction="row" flexWrap="wrap" gap={1}>
                {(data?.feelings ?? []).map((f) => {
                  const on = feelings.includes(f.key);
                  return <Chip key={f.key} label={f.label} clickable color={on ? "primary" : "default"} variant={on ? "filled" : "outlined"}
                    onClick={() => setFeelings(on ? feelings.filter((x) => x !== f.key) : [...feelings, f.key])} aria-pressed={on} />;
                })}
              </Stack>
            </Box>
            <TextField label="Want to tell us more? (optional)" multiline minRows={2} value={note} onChange={(e) => setNote(e.target.value)}
              inputProps={{ maxLength: 500 }} />
            <FormControlLabel control={<Checkbox checked={contact} onChange={(e) => setContact(e.target.checked)} />}
              label="I'd like someone from my care team to contact me" />
            <Typography variant="caption" color="text.secondary">For emergencies call 911. If you're thinking about harming yourself, call or text 988.</Typography>
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {reply ? <Button variant="contained" onClick={close} size="large">Continue</Button> : (
          <>
            <Button onClick={close}>Not now</Button>
            <Button variant="contained" onClick={submit} disabled={!mood || busy} size="large">Share</Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
