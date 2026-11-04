import LocalHospitalRounded from "@mui/icons-material/LocalHospitalRounded";
import {
  Alert, Box, Button, Card, CardContent, Chip, Divider, Stack, TextField, Typography,
} from "@mui/material";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiBase, isNativeApp } from "../api/client";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Disclaimer } from "../components/Layout";

// Demo accounts (synthetic). Passwords are documented in README for local use only.
const DEMO = [
  { email: "patient@example.com", label: "Patient (Jordan, knee replacement)" },
  { email: "caregiver@example.com", label: "Caregiver (Casey)" },
  { email: "nurse@example.com", label: "Nurse / care manager" },
  { email: "doctor@example.com", label: "Doctor / surgeon" },
  { email: "admin@example.com", label: "Administrator" },
];

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const native = isNativeApp();
  const [server, setServer] = useState(() => apiBase.get());

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    if (native) apiBase.set(server.trim() || null);
    try {
      const u = await login(email, password);
      nav(homeFor(u.role), { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <Disclaimer />
      <Stack alignItems="center" justifyContent="center" sx={{ px: 2, py: { xs: 4, md: 8 } }}>
        <Card sx={{ width: "100%", maxWidth: 440 }}>
          <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
            <Stack direction="row" alignItems="center" gap={1.5} mb={1}>
              <LocalHospitalRounded color="primary" fontSize="large" aria-hidden />
              <Typography variant="h5" component="h1">Recovery Companion</Typography>
            </Stack>
            <Typography color="text.secondary" mb={3}>
              Your guide for the first 30 days after surgery.
            </Typography>
            <Box component="form" onSubmit={submit} noValidate>
              <Stack gap={2}>
                {error && <Alert severity="error" role="alert">{error}</Alert>}
                <TextField label="Email" type="email" autoComplete="username" value={email}
                  onChange={(e) => setEmail(e.target.value)} required fullWidth autoFocus />
                <TextField label="Password" type="password" autoComplete="current-password" value={password}
                  onChange={(e) => setPassword(e.target.value)} required fullWidth />
                {native && (
                  <TextField label="Server address" value={server} onChange={(e) => setServer(e.target.value)} fullWidth size="small"
                    helperText="The Recovery Companion API, e.g. https://recovery.example.org/api" inputProps={{ autoCapitalize: "none", inputMode: "url" }} />
                )}
                <Button type="submit" variant="contained" size="large" disabled={busy || !email || !password}>
                  {busy ? "Signing in…" : "Sign in"}
                </Button>
              </Stack>
            </Box>
            <Divider sx={{ my: 3 }}>Synthetic demo accounts</Divider>
            <Stack direction="row" flexWrap="wrap" gap={1}>
              {DEMO.map((d) => (
                <Chip key={d.email} label={d.label} variant="outlined" clickable onClick={() => setEmail(d.email)} />
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" mt={1.5}>
              Choose an account to fill the email; the local development password is in the README.
            </Typography>
          </CardContent>
        </Card>
      </Stack>
    </Box>
  );
}
