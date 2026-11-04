import { createTheme } from "@mui/material/styles";

// Calm clinical palette. Severity colors are always paired with an icon + text label.
export const severityColors = {
  RED: { main: "#b42318", bg: "#fef3f2", border: "#fda29b" },
  AMBER: { main: "#9a5b00", bg: "#fffaeb", border: "#fec84b" },
  GREEN: { main: "#067647", bg: "#ecfdf3", border: "#75e0a7" },
  INFO: { main: "#175cd3", bg: "#eff8ff", border: "#84caff" },
} as const;

export const theme = createTheme({
  palette: {
    primary: { main: "#0b6e75", contrastText: "#ffffff" },
    secondary: { main: "#3e4784" },
    error: { main: severityColors.RED.main },
    warning: { main: "#b54708" },
    success: { main: severityColors.GREEN.main },
    background: { default: "#f5f7f8", paper: "#ffffff" },
    text: { primary: "#101828", secondary: "#475467" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif',
    h4: { fontWeight: 700, letterSpacing: -0.4 },
    h5: { fontWeight: 700, letterSpacing: -0.2 },
    h6: { fontWeight: 650 },
    subtitle1: { fontWeight: 600 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiCard: { defaultProps: { variant: "outlined" }, styleOverrides: { root: { borderColor: "#e4e7ec" } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiAppBar: { defaultProps: { elevation: 0 } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 700, color: "#344054", background: "#f9fafb" } } },
  },
});
