import {
    Links,
    Meta,
    Outlet,
    Scripts,
    ScrollRestoration,
    isRouteErrorResponse,
} from "react-router";
import { CssBaseline, ThemeProvider } from "@mui/material";
import type { Route } from "./+types/root";
import { theme } from "./theme";
import "./app.css";
import { LanguageProvider } from "./i18n";
import { AuthProvider } from "./auth";

export function Layout({ children }: { children: React.ReactNode }) {
    return (
        <html lang="en">
            <head>
                <meta charSet="utf-8" />
                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                />
                <meta name="theme-color" content="#101b2d" />
                <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
                <title>GoodNight · UESTC</title>
                <Meta />
                <Links />
            </head>
            <body>
                {children}
                <ScrollRestoration />
                <Scripts />
            </body>
        </html>
    );
}

export function HydrateFallback() {
    return (
        <main
            style={{
                padding: "48px",
                color: "#f3f4ed",
                fontFamily: "system-ui",
            }}
            role="status"
        >
            Loading GoodNight…
        </main>
    );
}

export default function App() {
    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <AuthProvider>
                <LanguageProvider>
                    <Outlet />
                </LanguageProvider>
            </AuthProvider>
        </ThemeProvider>
    );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
    const notFound = isRouteErrorResponse(error) && error.status === 404;
    return (
        <main
            style={{
                padding: "48px",
                color: "#f3f4ed",
                fontFamily: "system-ui",
            }}
        >
            <h1>{notFound ? "Page not found" : "Something went wrong"}</h1>
            <p>
                {notFound
                    ? "This page does not exist."
                    : "Reload the console to try again."}
            </p>
            <a href="/" style={{ color: "#b9d99d" }}>
                Return to GoodNight
            </a>
        </main>
    );
}
