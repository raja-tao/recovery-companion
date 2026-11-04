import FamilyRestroomRounded from "@mui/icons-material/FamilyRestroomRounded";
import {
  Alert, Box, Button, Card, CardContent, Checkbox, Chip, FormControlLabel, FormGroup, Stack, TextField, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDateTime, Loading, PageHeader, Section } from "../../components/common";

interface Cg { id: string; name: string; email: string; relationship: string; status: string; authorized_at: string; revoked_at: string | null; scopes: string[] }

export default function Caregivers() {
  const { user } = useAuth();
  const pid = user!.patient_id;
  const { data, error, loading, reload } = useApi<{ caregivers: Cg[]; available_scopes: Record<string, string> }>(`/patients/${pid}/caregivers`);
  const [email, setEmail] = useState("caregiver2@example.com");
  const [rel, setRel] = useState("Family member");
  const [scopes, setScopes] = useState<string[]>(["RECOVERY_STATUS", "PROGRESS"]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} />;

  async function authorize() {
    try {
      await api(`/patients/${pid}/caregivers`, { body: { caregiver_email: email, relationship_to_patient: rel, scopes } });
      setMsg({ ok: true, text: `Access granted to ${email}.` });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }
  async function revoke(c: Cg) {
    await api(`/patients/${pid}/caregivers/${c.id}`, { method: "DELETE" });
    setMsg({ ok: true, text: `Access for ${c.name} revoked immediately.` });
    reload();
  }

  return (
    <Stack gap={2.5} maxWidth={860} mx="auto">
      <PageHeader title="Caregiver access" subtitle="You decide what a family member or friend can see. You can revoke access at any time." />
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Alert severity="info">Caregivers never see your clinical notes, check-in answers, care-team notes or full medical history.</Alert>
      {data.caregivers.map((c) => (
        <Card key={c.id}><CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={1}>
            <Stack direction="row" gap={1.5}>
              <FamilyRestroomRounded color="primary" />
              <Box>
                <Typography variant="subtitle1">{c.name} · {c.relationship}</Typography>
                <Typography variant="body2" color="text.secondary">{c.email} · authorized {fmtDateTime(c.authorized_at)}</Typography>
                <Stack direction="row" gap={0.75} mt={1} flexWrap="wrap">
                  {c.status === "ACTIVE" ? c.scopes.map((s) => <Chip key={s} size="small" label={data.available_scopes[s] ?? s} />)
                    : <Chip size="small" label={`Revoked ${fmtDateTime(c.revoked_at)}`} />}
                </Stack>
              </Box>
            </Stack>
            {c.status === "ACTIVE" && <Button color="error" variant="outlined" onClick={() => revoke(c)}>Revoke access</Button>}
          </Stack>
        </CardContent></Card>
      ))}
      <Section title="Add a caregiver" id="add">
        <Stack gap={2}>
          <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
            <TextField label="Caregiver's email" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth helperText="They need a caregiver account" />
            <TextField label="Relationship" value={rel} onChange={(e) => setRel(e.target.value)} fullWidth />
          </Stack>
          <Typography fontWeight={600}>What can they see?</Typography>
          <FormGroup>
            {Object.entries(data.available_scopes).map(([k, label]) => (
              <FormControlLabel key={k} label={label} control={
                <Checkbox checked={scopes.includes(k)} onChange={() => setScopes(scopes.includes(k) ? scopes.filter((s) => s !== k) : [...scopes, k])} />
              } />
            ))}
          </FormGroup>
          <Button variant="contained" onClick={authorize} disabled={!email || scopes.length === 0} sx={{ alignSelf: "flex-start" }}>Grant access</Button>
        </Stack>
      </Section>
    </Stack>
  );
}
