import ArticleRounded from "@mui/icons-material/ArticleRounded";
import PhoneInTalkRounded from "@mui/icons-material/PhoneInTalkRounded";
import SendRounded from "@mui/icons-material/SendRounded";
import SmartToyRounded from "@mui/icons-material/SmartToyRounded";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Avatar, Box, Button, Chip, IconButton, Paper, Stack, TextField,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, useApi } from "../../api/client";
import type { ChatResponse, Citation, Message, Severity } from "../../api/types";
import { SeverityChip, titleCase } from "../../components/common";

interface Turn { role: "user" | "assistant"; text: string; meta?: Partial<ChatResponse> & { citations?: Citation[]; actions?: string[] } }

const SUGGESTIONS = ["When can I drive?", "Can I shower?", "When should I start PT?", "What should I do about swelling?",
  "What does my recovery plan say about sleeping position?", "I forgot my pain medicine. Should I take two now?"];

export default function Assistant() {
  const [params] = useSearchParams();
  const history = useApi<Message[]>("/ai/conversation");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  useEffect(() => {
    if (history.data && turns.length === 0) {
      setTurns(history.data.slice(-20).map((m) => ({
        role: m.sender_type === "PATIENT" ? "user" : "assistant", text: m.content,
        meta: { citations: m.citations, safety_level: (m.safety_level ?? undefined) as Severity | undefined, actions: m.actions,
          answered_from_content: m.answered_from_content ?? undefined },
      })));
    }
  }, [history.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const q = params.get("q");
    if (q && !asked.current && history.data) {
      asked.current = true;
      send(q);
    }
  }, [params, history.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [turns, busy]);

  async function send(text: string) {
    if (!text.trim()) return;
    setErr(null);
    setTurns((t) => [...t, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api<ChatResponse>("/ai/chat", { body: { message: text } });
      setTurns((t) => [...t, { role: "assistant", text: r.answer, meta: r }]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); send(input); };

  return (
    <Stack gap={2} sx={{ maxWidth: 820, mx: "auto" }}>
      <Box>
        <Typography variant="h4" component="h1">Recovery assistant</Typography>
        <Typography color="text.secondary">
          Answers come only from your surgeon- and hospital-approved instructions, with the source shown.
          It can't diagnose or change your treatment.
        </Typography>
      </Box>
      <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2 }, minHeight: 360, bgcolor: "#fcfcfd" }} aria-live="polite" aria-label="Conversation">
        {turns.length === 0 && (
          <Stack alignItems="center" gap={2} py={4}>
            <Avatar sx={{ bgcolor: "primary.main", width: 56, height: 56 }}><SmartToyRounded /></Avatar>
            <Typography color="text.secondary" textAlign="center">Ask a question about your recovery instructions.</Typography>
          </Stack>
        )}
        <Stack gap={2}>
          {turns.map((t, i) => <Bubble key={i} turn={t} />)}
          {busy && <Typography color="text.secondary" fontStyle="italic">Checking your approved instructions…</Typography>}
          <div ref={endRef} />
        </Stack>
      </Paper>
      {err && <Alert severity="error">{err}</Alert>}
      <Stack direction="row" gap={1} flexWrap="wrap">
        {SUGGESTIONS.map((s) => <Chip key={s} label={s} onClick={() => send(s)} clickable variant="outlined" disabled={busy} />)}
      </Stack>
      <Box component="form" onSubmit={submit} sx={{ display: "flex", gap: 1 }}>
        <TextField fullWidth placeholder="Type your question…" value={input} onChange={(e) => setInput(e.target.value)}
          inputProps={{ maxLength: 1000, "aria-label": "Your question" }} disabled={busy} />
        <IconButton type="submit" color="primary" disabled={busy || !input.trim()} aria-label="Send" size="large"><SendRounded /></IconButton>
      </Box>
    </Stack>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  const user = turn.role === "user";
  const m = turn.meta;
  return (
    <Stack direction="row" justifyContent={user ? "flex-end" : "flex-start"}>
      <Box sx={{ maxWidth: { xs: "92%", sm: "80%" } }}>
        {m?.emergency && (
          <Alert severity="error" variant="filled" sx={{ mb: 1 }} role="alert"
            action={<Button color="inherit" href="tel:911" startIcon={<PhoneInTalkRounded />}>Call 911</Button>}>
            Possible emergency
          </Alert>
        )}
        <Paper elevation={0} sx={{
          p: 1.75, borderRadius: 3, bgcolor: user ? "primary.main" : "#fff", color: user ? "#fff" : "text.primary",
          border: user ? undefined : "1px solid #e4e7ec", borderTopRightRadius: user ? 4 : undefined, borderTopLeftRadius: user ? undefined : 4,
        }}>
          <Typography className="prewrap">{turn.text}</Typography>
        </Paper>
        {!user && m && (
          <Stack gap={1} mt={0.75}>
            <Stack direction="row" gap={0.75} flexWrap="wrap" alignItems="center">
              {m.safety_level && <SeverityChip level={m.safety_level} />}
              {m.answered_from_content === true && <Chip size="small" color="success" variant="outlined" label="From approved content" />}
              {m.answered_from_content === false && m.intent !== "GREETING" && <Chip size="small" variant="outlined" label="Not answered — routed to care team" />}
              {(m.actions ?? []).filter((a) => a.includes("task") || a.includes("alert") || a.includes("review")).map((a) => <Chip key={a} size="small" label={a} />)}
            </Stack>
            {(m.citations ?? []).map((c, i) => (
              <Accordion key={i} disableGutters variant="outlined" sx={{ borderRadius: 2, "&:before": { display: "none" } }}>
                <AccordionSummary expandIcon={<ArticleRounded fontSize="small" />} aria-label={`Source: ${c.title}, ${c.section}`}>
                  <Box>
                    <Typography variant="body2" fontWeight={600}>Source: {c.title}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Section “{c.section}”{c.version ? ` · v${c.version}` : ""}{c.authority ? ` · ${titleCase(c.authority)}` : ""}
                      {c.approved_by ? ` by ${c.approved_by}` : ""}{c.score != null ? ` · match ${(c.score * 100).toFixed(0)}%` : ""}
                    </Typography>
                  </Box>
                </AccordionSummary>
                {c.excerpt && <AccordionDetails><Typography variant="body2" className="prewrap" color="text.secondary">{c.excerpt}</Typography></AccordionDetails>}
              </Accordion>
            ))}
            {m.model !== undefined && (
              <Typography variant="caption" color="text.secondary">
                {m.provider ? `Answered by ${m.provider}${m.model ? ` (${m.model})` : ""}` : ""}{m.prompt_version ? ` · prompt ${m.prompt_version}` : ""}
              </Typography>
            )}
          </Stack>
        )}
      </Box>
    </Stack>
  );
}
