import { useEffect } from "react";
import { CircularProgress } from "@mui/material";

export default function PageRedirect({ to }: { to: string }) {
    useEffect(() => {
        window.location.replace(to);
    }, [to]);
    return <CircularProgress sx={{ m: 3 }} />;
}
