import { Alert, Button, CircularProgress } from "@mui/material";
import { Outlet, useLocation } from "react-router";
import PageRedirect from "../components/PageRedirect";
import { useAuth, userHomePath } from "../auth";
import { useLanguage } from "../i18n";

export default function ConsoleRoute() {
    const { user, loading, error, refresh } = useAuth();
    const { t } = useLanguage();
    const { pathname } = useLocation();
    if (loading) return <CircularProgress sx={{ m: 3 }} />;
    if (error)
        return (
            <Alert
                severity="error"
                action={
                    <Button onClick={() => void refresh()}>
                        {t("Retry", "重试")}
                    </Button>
                }
            >
                {error}
            </Alert>
        );
    if (!user) return <PageRedirect to="/login" />;
    const destination = userHomePath(user);
    if (pathname !== destination) return <PageRedirect to={destination} />;
    return <Outlet />;
}
