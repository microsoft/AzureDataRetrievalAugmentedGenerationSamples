package com.azure.recipe;

import com.azure.recipe.model.Recipe;
import com.azure.recipe.service.CosmosDbService;
import com.azure.recipe.service.OpenAIService;
import com.fasterxml.jackson.core.JsonProcessingException;
import lombok.extern.slf4j.Slf4j;

import java.io.IOException;
import java.util.List;
import java.util.Scanner;

@Slf4j
public class Main {
    public static CosmosDbService cosmosDbService = null;
    public static OpenAIService openAIEmbeddingService = null;

    public static void main(String[] args) throws IOException {

        Scanner scanner = new Scanner(System.in);

        cosmosDbService = initCosmosDbService();

        while (true) {
            System.out.println("\n");
            System.out.println("1.\tUpload and vectorize the recipe(s) and store it in Cosmos DB");
            System.out.println("2.\tAsk AI Assistant (search for a recipe by name or description, or ask a question)");
            System.out.println("3.\tExit this Application");
            System.out.print("Please select an option: ");
            int selectedOption = Integer.parseInt(scanner.nextLine());
            switch (selectedOption) {
                case 1 -> uploadRecipes();
                case 2 -> performSearch(scanner);
                default -> System.exit(0);
            }
        }
    }

    private static CosmosDbService initCosmosDbService() {
        CosmosDbService cosmosDbService = new CosmosDbService(AppConfig.cosmosUri,
                AppConfig.cosmosKey,
                AppConfig.cosmosDatabase,
                AppConfig.cosmosContainer
        );
        int recipeWithEmbedding = cosmosDbService.getRecipeCount(true);
        int recipeWithNoEmbedding = cosmosDbService.getRecipeCount(false);

        System.out.println("\n");
        System.out.printf("We have %d vectorized recipe(s) and %d non vectorized recipe(s).",
                recipeWithEmbedding, recipeWithNoEmbedding);

        return cosmosDbService;
    }

    private static OpenAIService initOpenAIService() {
        return new OpenAIService(AppConfig.openAIEndpoint,
                AppConfig.openAIKey,
                AppConfig.openAIEmbeddingDeployment,
                AppConfig.openAICompletionsDeployment,
                AppConfig.openAIMaxToken);
    }

    public static void uploadRecipes() throws JsonProcessingException {
        List<Recipe> recipes = Utility.parseDocuments(AppConfig.recipeLocalFolder);
        uploadAndVectorizeDocs(recipes);
    }

    public static void performSearch(Scanner scanner) throws JsonProcessingException {

        if (openAIEmbeddingService == null) {
            log.info("Connecting to Open AI Service..");
            openAIEmbeddingService = initOpenAIService();
        }

        System.out.println("Type the recipe name or your question, hit enter when ready.");
        String userQuery = scanner.nextLine();

        log.info("Converting User Query to Vector..");
        var embeddingVector = openAIEmbeddingService.getEmbeddings(userQuery);

        log.info("Performing Vector Search in Cosmos DB NoSQL API..");
        Iterable<Recipe> filteredRecipes = cosmosDbService.vectorSearch(embeddingVector);

        for (Recipe recipe : filteredRecipes) {
            log.info(String.format("Query result: Recipe with (/id, partition key) = (%s,%s)", recipe.getId(), recipe.getId()));
        }

        log.info("Retrieving recipe(s) from Cosmos DB (RAG pattern)..");

        StringBuilder retrievedRecipeNames = new StringBuilder();

        for (Recipe recipe : filteredRecipes) {
            retrievedRecipeNames.append(", ").append(recipe.name); //to display recipes submitted for Completion
        }

        log.info("Processing '{}' to generate Completion using OpenAI Service..", retrievedRecipeNames);

        String chatCompletion = openAIEmbeddingService
                .getChatCompletionAsync(userQuery, Utility.OBJECT_MAPPER.writeValueAsString(filteredRecipes));

        log.info("AI Assistant Response: {}", chatCompletion);
        System.out.println(chatCompletion);
    }

    private static void uploadAndVectorizeDocs(List<Recipe> recipes) throws JsonProcessingException {
        int recipeWithEmbedding = 0;
        int recipeWithNoEmbedding = 0;
        int recipeCount = 0;

        if (openAIEmbeddingService == null) {
            openAIEmbeddingService = initOpenAIService();
        }

        log.info("Getting recipe(s) to vectorize..");
        for (Recipe recipe : recipes) {
            recipe.setId(recipe.getName().replace(" ", ""));
            recipeCount++;
            log.info("Vectorizing Recipe# {}..", recipeCount);
            var embeddingVector = openAIEmbeddingService.getEmbeddings(Utility.OBJECT_MAPPER.writeValueAsString(recipe));
            recipe.embedding = embeddingVector;
        }

        log.info("Updating {} recipe(s) in Cosmos DB for vectors..", recipes.size());

        cosmosDbService.uploadRecipes(recipes);

        log.info("Getting Updated Recipe Stats");
        recipeWithEmbedding = cosmosDbService.getRecipeCount(true);
        recipeWithNoEmbedding = cosmosDbService.getRecipeCount(false);

        log.info("Vectorized {} recipe(s).", recipeCount);
        System.out.println("\n");
        System.out.printf("We have %d vectorized recipe(s) and %d non vectorized recipe(s).",
                recipeWithEmbedding, recipeWithNoEmbedding);
    }

}