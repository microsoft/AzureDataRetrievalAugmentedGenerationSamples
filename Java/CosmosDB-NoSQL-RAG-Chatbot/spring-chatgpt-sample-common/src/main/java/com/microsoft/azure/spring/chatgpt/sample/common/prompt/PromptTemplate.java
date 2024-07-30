package com.microsoft.azure.spring.chatgpt.sample.common.prompt;

import java.util.List;

public class PromptTemplate {

    private static final String template = """
            Context information is below.
            ---------------------
            %s
            ---------------------
            Given the context information and not prior knowledge, answer the question: %s
            """;

    public static String formatWithContext(List<String> context, String question) {
        String merged = String.join("\n", context);
        return String.format(template, merged, question);
    }
}
