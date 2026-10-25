# IDAS password encoding

Verified on 2026-10-25 against the public UESTC login page, asset version
`20260910.204435`. No real account credentials were submitted.

Sources:
- https://idas.uestc.edu.cn/authserver/login
- https://idas.uestc.edu.cn/authserver/uestcTheme/static/web/js/login.js?v=20260910.204435
- https://idas.uestc.edu.cn/authserver/uestcTheme/static/common/encrypt.js?v=20260910.204435

The call chain is `startLogin → checkForm → encryptPassword → encryptAES →
getAesString → CryptoJS.AES.encrypt`.

1. Read the active login form's `pwdEncryptSalt`. Despite the name, its trimmed
   UTF-8 bytes are the AES key directly, with no password-based key derivation.
   The observed form uses 16 ASCII characters, so this is AES-128.
2. Generate 64 random ASCII characters and prepend them to the unchanged password.
3. Generate another 16 random ASCII characters as the CBC IV.
4. UTF-8 encode the prefixed password, PKCS#7-pad to 16-byte blocks, then AES-CBC encrypt.
5. Base64-encode the ciphertext only. This raw-key CryptoJS path does not prepend
   an OpenSSL salt header or serialize the IV.
6. Write the result to `#saltPassword` (hidden field named `password`), disable
   the visible `#password` (named `passwordText`), and submit the form. The
   normal form encoder then escapes Base64 characters such as `+`, `/`, and `=`.

The random alphabet is `ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678`.
The site's generator samples it with `Math.random()`. The Python implementation
uses `secrets.choice` over the same alphabet; ciphertexts follow the same format.
Neither the username, browser fingerprint, SMS code nor the Unix timestamp is an
input to this encryption function. They belong to other parts of authentication.

Both the random prefix/IV and a changed page key can change the submitted string.
Never reuse a captured ciphertext or hard-code a page key or `execution` value.
Use all hidden form values and cookies from the same login attempt.

CBC inference: although the IV is not transmitted, it only affects decryption
of the first block when the server starts with another IV. Password bytes follow
four random blocks. Discarding the first 64 bytes would therefore recover the
password independently of the first block. This explains the wire format; the
server implementation itself has not been inspected.

`uestc_login.crypto.encrypt_password` implements the transform and matches three
vectors produced by executing the downloaded, unmodified CryptoJS script with
synthetic ASCII, Unicode, and block-boundary passwords. Production HTTP login
uses this Python transform with the current page key and form fields. The optional
CAPTCHA check and human gesture relay use HTTP when enabled. The helper fails
closed on an invalid/missing key instead of copying the site's plaintext fallback.
