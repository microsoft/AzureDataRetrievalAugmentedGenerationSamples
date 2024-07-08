package com.microsoft.azure.spring.chatgpt.sample.common;

import com.microsoft.azure.spring.chatgpt.sample.common.reader.SimpleFolderReader;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosDBVectorStore;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosEntity;

import java.io.IOException;
import java.util.List;
import java.util.UUID;
import java.util.logging.Logger;

public class DocumentIndexPlanner {
    public DocumentIndexPlanner(AzureOpenAIClient client, CosmosDBVectorStore vectorStore) {
        this.client = client;
        this.vectorStore = vectorStore;
    }
    private final AzureOpenAIClient client;
    private final CosmosDBVectorStore vectorStore;

    private Logger log = Logger.getLogger(DocumentIndexPlanner.class.getName());
    public void buildFromFolder(String folderPath) throws IOException {
        if (folderPath == null) {
            throw new IllegalArgumentException("folderPath shouldn't be empty.");
        }
        final int[] dimensions = {0};
        vectorStore.createVectorIndex(100, dimensions[0], "COS");
        SimpleFolderReader reader = new SimpleFolderReader(folderPath);
        TextSplitter splitter = new TextSplitter();

        reader.run((fileName, content) -> {

            log.info("String to process: "+ fileName);
            var textChunks = splitter.split(content);
            for (var chunk: textChunks) {
                try {
                    //sleep to help avoid azure openai rate limiting for P0 tier
                    //remove this if you a higher rate limit
                    log.info("Sleeping for 5000ms to avoid Azure OpenAI rate limiting");
                    Thread.sleep(5000);
                } catch (InterruptedException e) {
                    throw new RuntimeException(e);
                }
                var response = client.getEmbeddings(List.of(chunk));
                var embedding = response.getData().get(0).getEmbedding();
                if (dimensions[0] == 0) {
                    dimensions[0] = embedding.size();
                } else if (dimensions[0] != embedding.size()) {
                    throw new IllegalStateException("Embedding size is not consistent.");
                }
                String key = UUID.randomUUID().toString();
                CosmosEntity docEntry = new CosmosEntity(key, "", chunk,  embedding);
                vectorStore.saveDocument(key, docEntry);
            }
            return null;
        });

        log.info("All documents are loaded to Cosmos DB NoSQL API vector store.");
    }
}
