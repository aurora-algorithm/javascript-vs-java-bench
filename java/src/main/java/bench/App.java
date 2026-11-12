package bench;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class App {
    public static void main(String[] args) {
        // Kept in the session log: the CPU count the JVM sees under the core pinning.
        System.out.println("java " + Runtime.version() + ", availableProcessors " + Runtime.getRuntime().availableProcessors());
        SpringApplication.run(App.class, args);
    }
}
