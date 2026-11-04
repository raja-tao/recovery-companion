import SendRounded from "@mui/icons-material/SendRounded";
import { Alert, Box, IconButton, Paper, Stack, TextField, Typography } from "@mui/material";
import { useState, type FormEvent } from "react";
import { api, useApi } from "../../api/client";
import type { Message } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader } from "../../components/common";

export function MessageThread({ patientId, staff = false }: { patientId: string; staff?: boolean }) {
  const { data, error, loading, reload } = useApi<Message[]>(`/patients/${patientId}/messages`);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} />;

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    await api(`/patients/${patientId}/messages`, { body: { content: text } });
    setText("");
    setBusy(false);
    reload();
  }

  return (
    <Stack gap={2}>
      <Paper variant="outlined" sx={{ p: 2, minHeight: 240, bgcolor: "#fcfcfd" }}>
        {data.length === 0 && <EmptyState text="No messages yet." />}
        <Stack gap={1.5}>
          {data.map((m) => {
            const mine = staff ? m.sender_type === "CARE_TEAM" : m.sender_type === "PATIENT";
            return (
              <Box key={m.id} alignSelf={mine ? "flex-end" : "flex-start"} maxWidth="80%">
                <Paper elevation={0} sx={{ p: 1.5, borderRadius: 3, bgcolor: mine ? "primary.main" : "#fff", color: mine ? "#fff" : undefined, border: mine ? undefined : "1px solid #e4e7ec" }}>
                  <Typography className="prewrap">{m.content}</Typography>
                </Paper>
                <Typography variant="caption" color="text.secondary">{m.sender_name} · {fmtDateTime(m.created_at)}</Typography>
              </Box>
            );
          })}
        </Stack>
      </Paper>
      <Box component="form" onSubmit={send} sx={{ display: "flex", gap: 1 }}>
        <TextField fullWidth size="small" placeholder={staff ? "Message the patient…" : "Message your care team…"} value={text}
          onChange={(e) => setText(e.target.value)} inputProps={{ maxLength: 2000, "aria-label": "Message" }} />
        <IconButton type="submit" color="primary" disabled={busy || !text.trim()} aria-label="Send"><SendRounded /></IconButton>
      </Box>
    </Stack>
  );
}

export default function Messages() {
  const { user } = useAuth();
  return (
    <Stack gap={2} maxWidth={800} mx="auto">
      <PageHeader title="Messages" subtitle="Secure messages with your care team. Replies within one business day." />
      <Alert severity="warning">Messages are not monitored 24/7. For urgent problems call the nurse line; in an emergency call 911.</Alert>
      <MessageThread patientId={user!.patient_id!} />
    </Stack>
  );
}
