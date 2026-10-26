"""Read only the password form; IDAS also renders hidden copies of other forms."""

from html.parser import HTMLParser


class PasswordForm(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.found = False
        self.action = ""
        self.fields = {}
        self.salt = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = attrs.get("id") == "pwdFromId"
            if self.active:
                self.found = True
                self.action = attrs.get("action", "")
        if tag == "input" and self.active:
            if attrs.get("id") == "pwdEncryptSalt":
                self.salt = attrs.get("value", "")
            if attrs.get("name") and attrs.get("type", "").lower() == "hidden":
                self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False
