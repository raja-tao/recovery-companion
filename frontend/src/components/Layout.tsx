import AirportShuttleRounded from "@mui/icons-material/AirportShuttleRounded";
import AssignmentRounded from "@mui/icons-material/AssignmentRounded";
import AutoAwesomeRounded from "@mui/icons-material/AutoAwesomeRounded";
import AssignmentTurnedInRounded from "@mui/icons-material/AssignmentTurnedInRounded";
import BarChartRounded from "@mui/icons-material/BarChartRounded";
import CableRounded from "@mui/icons-material/CableRounded";
import ChatRounded from "@mui/icons-material/ChatRounded";
import DescriptionRounded from "@mui/icons-material/DescriptionRounded";
import EventRounded from "@mui/icons-material/EventRounded";
import FactCheckRounded from "@mui/icons-material/FactCheckRounded";
import FamilyRestroomRounded from "@mui/icons-material/FamilyRestroomRounded";
import GavelRounded from "@mui/icons-material/GavelRounded";
import HomeRounded from "@mui/icons-material/HomeRounded";
import LocalHospitalRounded from "@mui/icons-material/LocalHospitalRounded";
import LogoutRounded from "@mui/icons-material/LogoutRounded";
import MedicationRounded from "@mui/icons-material/MedicationRounded";
import MenuBookRounded from "@mui/icons-material/MenuBookRounded";
import MenuRounded from "@mui/icons-material/MenuRounded";
import NotificationsRounded from "@mui/icons-material/NotificationsRounded";
import PeopleRounded from "@mui/icons-material/PeopleRounded";
import PlayCircleRounded from "@mui/icons-material/PlayCircleRounded";
import PolicyRounded from "@mui/icons-material/PolicyRounded";
import QuestionAnswerRounded from "@mui/icons-material/QuestionAnswerRounded";
import ReportProblemRounded from "@mui/icons-material/ReportProblemRounded";
import RouteRounded from "@mui/icons-material/RouteRounded";
import {
  AppBar, Badge, BottomNavigation, BottomNavigationAction, Box, Divider, Drawer, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Paper, Stack, Toolbar, Tooltip, Typography,
  useMediaQuery, useTheme,
} from "@mui/material";
import { useState, type ReactNode } from "react";
import { Link as RouterLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { fmtDateTime } from "./common";
import MoodPrompt from "./MoodPrompt";

type NavItem = { to: string; label: string; icon: ReactNode };

const NAV: Record<string, { section?: string; items: NavItem[] }[]> = {
  PATIENT: [{ items: [
    { to: "/patient", label: "Home", icon: <HomeRounded /> },
    { to: "/patient/checkin", label: "Daily check-in", icon: <FactCheckRounded /> },
    { to: "/patient/medications", label: "Medications", icon: <MedicationRounded /> },
    { to: "/patient/assistant", label: "Ask the assistant", icon: <QuestionAnswerRounded /> },
    { to: "/patient/plan", label: "Recovery plan", icon: <RouteRounded /> },
    { to: "/patient/appointments", label: "Appointments", icon: <EventRounded /> },
    { to: "/patient/surveys", label: "Recovery surveys", icon: <AssignmentRounded /> },
    { to: "/patient/education", label: "Education", icon: <MenuBookRounded /> },
    { to: "/patient/messages", label: "Messages", icon: <ChatRounded /> },
    { to: "/patient/caregivers", label: "Caregiver access", icon: <FamilyRestroomRounded /> },
  ] }],
  CAREGIVER: [{ items: [{ to: "/caregiver", label: "Shared recovery", icon: <HomeRounded /> }] }],
  NURSE: [
    { section: "Care team", items: [
      { to: "/care-team", label: "Worklist", icon: <ReportProblemRounded /> },
      { to: "/care-team/patients", label: "Patients", icon: <PeopleRounded /> },
      { to: "/care-team/transport", label: "Rides to visits", icon: <AirportShuttleRounded /> },
      { to: "/care-team/protocols", label: "Warning protocols", icon: <PolicyRounded /> },
    ] },
    { section: "Program", items: [
      { to: "/admin/analytics", label: "Analytics", icon: <BarChartRounded /> },
      { to: "/admin/demo", label: "Demo scenarios", icon: <PlayCircleRounded /> },
    ] },
  ],
  SURGEON: [{ section: "Doctor", items: [
    { to: "/surgeon", label: "Escalations", icon: <LocalHospitalRounded /> },
    { to: "/surgeon/approvals", label: "Plan approvals", icon: <AssignmentTurnedInRounded /> },
    { to: "/care-team", label: "Worklist", icon: <ReportProblemRounded /> },
    { to: "/care-team/patients", label: "Patients", icon: <PeopleRounded /> },
    { to: "/care-team/protocols", label: "Warning protocols", icon: <PolicyRounded /> },
    { to: "/admin/documents", label: "Content approval", icon: <DescriptionRounded /> },
  ] }],
  ADMIN: [{ section: "Administration", items: [
    { to: "/admin/analytics", label: "Analytics", icon: <BarChartRounded /> },
    { to: "/admin/ai-agents", label: "AI agents", icon: <AutoAwesomeRounded /> },
    { to: "/admin/integrations", label: "Integrations", icon: <CableRounded /> },
    { to: "/admin/documents", label: "Approved content", icon: <DescriptionRounded /> },
    { to: "/care-team/protocols", label: "Warning protocols", icon: <PolicyRounded /> },
    { to: "/admin/users", label: "Users & programs", icon: <PeopleRounded /> },
    { to: "/admin/audit", label: "Audit trail", icon: <GavelRounded /> },
    { to: "/admin/demo", label: "Demo scenarios", icon: <PlayCircleRounded /> },
  ] }],
};

const DRAWER = 248;

export function Disclaimer() {
  return (
    <Box role="note" sx={{ bgcolor: "#1d2939", color: "#fff", px: 2, py: 0.75, fontSize: 13, textAlign: "center", lineHeight: 1.4 }}>
      <Box component="span" sx={{ display: { xs: "inline", sm: "none" } }}>
        <strong>Synthetic-data POC · not for clinical use</strong> · Emergency: call 911
      </Box>
      <Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>
        <strong>Proof of concept — synthetic data only. Not for clinical use.</strong>{" "}
        This app explains approved recovery instructions; it does not diagnose or change treatment. In an emergency call 911.
      </Box>
    </Box>
  );
}

function Notifications() {
  const { data, reload } = useApi<{ unread: number; items: { id: string; title: string; body: string; created_at: string; read_at: string | null }[] }>("/notifications/me");
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <>
      <Tooltip title="Notifications">
        <IconButton color="inherit" aria-label={`Notifications, ${data?.unread ?? 0} unread`} onClick={(e) => { setAnchor(e.currentTarget); reload(); }}>
          <Badge badgeContent={data?.unread ?? 0} color="error"><NotificationsRounded /></Badge>
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => { setAnchor(null); api("/notifications/read-all", { method: "POST" }).then(reload); }}
        slotProps={{ paper: { sx: { width: 360, maxHeight: 440 } } }}>
        {(data?.items ?? []).length === 0 && <MenuItem disabled>No notifications</MenuItem>}
        {(data?.items ?? []).slice(0, 15).map((n) => (
          <MenuItem key={n.id} sx={{ whiteSpace: "normal", alignItems: "flex-start", bgcolor: n.read_at ? undefined : "#f0f9ff" }}>
            <Box>
              <Typography variant="subtitle2">{n.title}</Typography>
              <Typography variant="body2" color="text.secondary">{n.body}</Typography>
              <Typography variant="caption" color="text.secondary">{fmtDateTime(n.created_at)}</Typography>
            </Box>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up("md"));
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();
  if (!user) return null;
  const groups = NAV[user.role] ?? [];
  const isPatient = user.role === "PATIENT";
  const permanent = desktop && !isPatient;

  const drawer = (
    <Box sx={{ width: DRAWER }} role="navigation" aria-label="Main">
      <Toolbar />
      {groups.map((g, i) => (
        <List key={i} subheader={g.section ? <ListSubheader>{g.section}</ListSubheader> : undefined} dense>
          {g.items.map((it) => (
            <ListItemButton key={it.to} component={RouterLink} to={it.to} selected={loc.pathname === it.to} onClick={() => setOpen(false)}>
              <ListItemIcon sx={{ minWidth: 38 }}>{it.icon}</ListItemIcon>
              <ListItemText primary={it.label} />
            </ListItemButton>
          ))}
        </List>
      ))}
      <Divider />
      <List dense>
        <ListItemButton onClick={() => { logout(); nav("/login"); }}>
          <ListItemIcon sx={{ minWidth: 38 }}><LogoutRounded /></ListItemIcon>
          <ListItemText primary="Sign out" />
        </ListItemButton>
      </List>
    </Box>
  );

  const bottom = [
    { to: "/patient", label: "Home", icon: <HomeRounded /> },
    { to: "/patient/checkin", label: "Check-in", icon: <FactCheckRounded /> },
    { to: "/patient/medications", label: "Meds", icon: <MedicationRounded /> },
    { to: "/patient/assistant", label: "Ask", icon: <QuestionAnswerRounded /> },
    { to: "/patient/plan", label: "Plan", icon: <RouteRounded /> },
  ];

  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <a href="#main" className="skip-link">Skip to content</a>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: "primary.main", pt: "env(safe-area-inset-top)" }}>
        <Disclaimer />
        <Toolbar>
          {!permanent && (
            <IconButton color="inherit" edge="start" aria-label="Open menu" onClick={() => setOpen(true)} sx={{ mr: 1 }}>
              <MenuRounded />
            </IconButton>
          )}
          <LocalHospitalRounded sx={{ mr: 1 }} aria-hidden />
          <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 700 }} noWrap>
            Recovery Companion
          </Typography>
          <Notifications />
          <Stack sx={{ ml: 1, display: { xs: "none", sm: "flex" } }} alignItems="flex-end">
            <Typography variant="body2" fontWeight={600}>{user.full_name}</Typography>
            <Typography variant="caption" sx={{ opacity: 0.85 }}>{user.title ?? user.role.toLowerCase()}</Typography>
          </Stack>
          <Tooltip title="Sign out">
            <IconButton color="inherit" aria-label="Sign out" onClick={() => { logout(); nav("/login"); }} sx={{ ml: 1 }}>
              <LogoutRounded />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box sx={{ display: "flex", flex: 1 }}>
        {permanent ? (
          <Drawer variant="permanent" sx={{ width: DRAWER, flexShrink: 0, "& .MuiDrawer-paper": { width: DRAWER, pt: "34px" } }}>
            {drawer}
          </Drawer>
        ) : (
          <Drawer open={open} onClose={() => setOpen(false)} sx={{ "& .MuiDrawer-paper": { pt: "34px" } }}>{drawer}</Drawer>
        )}
        <Box component="main" id="main" tabIndex={-1}
          sx={{ flex: 1, minWidth: 0, pt: { xs: "104px", sm: "108px" }, pb: isPatient && !desktop ? 10 : 4, px: { xs: 2, md: 4 },
            maxWidth: isPatient ? 1100 : undefined, mx: isPatient ? "auto" : undefined, width: "100%" }}>
          {isPatient && <MoodPrompt onRecorded={() => window.dispatchEvent(new Event("rc:mood"))} />}
          <Outlet />
        </Box>
      </Box>
      {isPatient && !desktop && (
        <Paper sx={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 10, pb: "env(safe-area-inset-bottom)" }} elevation={8}>
          <BottomNavigation showLabels value={bottom.findIndex((b) => b.to === loc.pathname)} onChange={(_, i) => nav(bottom[i].to)}>
            {bottom.map((b) => <BottomNavigationAction key={b.to} label={b.label} icon={b.icon} />)}
          </BottomNavigation>
        </Paper>
      )}
    </Box>
  );
}
