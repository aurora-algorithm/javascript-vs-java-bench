package bench;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

@RestController
public class LoginController {
    record User(int id, String email, String hash) {}
    record LoginRequest(String email, String password) {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    record LoginResult(boolean ok, Integer id) {}

    private static final LoginResult DENIED = new LoginResult(false, null);

    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final Map<String, User> users;

    public LoginController() throws IOException {
        String file = System.getenv().getOrDefault("USERS", "../data/users.json");
        List<User> list = JsonMapper.builder().build().readValue(Files.readString(Path.of(file)), new TypeReference<List<User>>() {});
        users = list.stream().collect(Collectors.toUnmodifiableMap(User::email, Function.identity()));
    }

    @GetMapping(value = "/health", produces = MediaType.TEXT_PLAIN_VALUE)
    public String health() {
        return "ok";
    }

    @PostMapping("/login")
    public ResponseEntity<LoginResult> login(@RequestBody LoginRequest req) {
        User user = users.get(req.email());
        if (user == null || req.password() == null) {
            return ResponseEntity.status(401).body(DENIED);
        }
        boolean ok = encoder.matches(req.password(), user.hash());
        if (!ok) {
            return ResponseEntity.status(401).body(DENIED);
        }
        return ResponseEntity.ok(new LoginResult(true, user.id()));
    }
}
