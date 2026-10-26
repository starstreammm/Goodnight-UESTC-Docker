import { createTheme } from "@mui/material";

export const theme = createTheme({
    palette: {
        mode: "dark",
        primary: { main: "#b9d99d" },
        background: { default: "#101b2d", paper: "#18263a" },
        text: { primary: "#f3f4ed", secondary: "#a4b2c6" },
    },
    typography: {
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        h3: { fontWeight: 650, letterSpacing: "-.04em" },
        button: { textTransform: "none", fontWeight: 600 },
    },
    shape: { borderRadius: 14 },
    components: {
        MuiButton: { defaultProps: { disableElevation: true } },
        MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
    },
});
