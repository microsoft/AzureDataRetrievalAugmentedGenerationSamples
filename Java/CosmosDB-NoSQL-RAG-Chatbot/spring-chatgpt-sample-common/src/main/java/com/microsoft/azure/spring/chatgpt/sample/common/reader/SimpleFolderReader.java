package com.microsoft.azure.spring.chatgpt.sample.common.reader;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.function.BiFunction;

public class SimpleFolderReader {

    public SimpleFolderReader(String from) {
        this.from = from;
    }

    private final String from;

    private final List<String> allowedExts = List.of("txt", "md");

    public void run(BiFunction<String, String, Void> handler) throws IOException {
        Files.walk(Paths.get(from))
                .filter(Files::isRegularFile)
                .forEach(file -> {
                    String fileName = file.getFileName().toString();
                    String ext = getFileExtension(fileName);
                    if (allowedExts.contains(ext)) {
                        try {
                            String content = Files.readString(file);
                            handler.apply(fileName, content);
                        } catch (IOException e) {
                            e.printStackTrace();
                        }
                    }
                });
    }

    private static String getFileExtension(String fileName) {
        int dotIndex = fileName.lastIndexOf('.');

        if (dotIndex > 0 && dotIndex < fileName.length() - 1) {
            return fileName.substring(dotIndex + 1);
        } else {
            return "";
        }
    }
}
