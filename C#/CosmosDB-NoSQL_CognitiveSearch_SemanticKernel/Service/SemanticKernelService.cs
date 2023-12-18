using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Azure.AI.OpenAI;
using Azure.Core;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.SemanticKernel.TemplateEngine;
using static System.Runtime.InteropServices.JavaScript.JSType;
using Microsoft.Extensions.Logging;
using System.Runtime;
using Newtonsoft.Json;
using Microsoft.SemanticKernel;
using Microsoft.SemanticKernel.ChatCompletion;
using Microsoft.SemanticKernel.Memory;
using Microsoft.SemanticKernel.Connectors.OpenAI;
using Microsoft.SemanticKernel.Connectors.Memory.AzureAISearch;


namespace CosmosRecipeGuide.Services
{
    public class SemanticKernelService
    {
        //following lines supress errors tagged as "Feature is for evaluation purposes only and is subject to change or removal in future updates."
#pragma warning disable SKEXP0021 // Disable the warning for the next line
#pragma warning disable SKEXP0011 // Disable the warning for the next line
#pragma warning disable SKEXP0003 // Disable the warning for the next line
#pragma warning disable SKEXP0052 // Disable the warning for the next line

        readonly Kernel kernel;
        private const string MemoryCollectionName = "SKRecipe";

        ISemanticTextMemory memoryWithACS;
        IChatCompletionService chatCompletionService;

        public SemanticKernelService(string OpenAIEndpoint, string OpenAIKey, string EmbeddingsDeployment, string CompletionDeployment, string ACSEndpoint, string ACSApiKey)
        {

            memoryWithACS = new MemoryBuilder()
                .WithAzureOpenAITextEmbeddingGeneration(EmbeddingsDeployment,OpenAIEndpoint, OpenAIKey, "")
                .WithMemoryStore(new AzureAISearchMemoryStore(ACSEndpoint, ACSApiKey))
                .Build();

            chatCompletionService = new AzureOpenAIChatCompletionService(
                CompletionDeployment,                
                OpenAIEndpoint,
                OpenAIKey);        
        }


        public async Task SaveEmbeddingsAsync(string data, string id)
        {
            try
            {
                await memoryWithACS.SaveReferenceAsync(
                    collection: MemoryCollectionName,
                    externalSourceName: "Recipe",
                    externalId: id,
                    description:data,
                    text: data);

            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.ToString());   
            }
        }

        public async Task<List<string>> SearchEmbeddingsAsync(string query)
        {

            var memoryResults = memoryWithACS.SearchAsync(MemoryCollectionName, query, limit: 3, minRelevanceScore: 0.5);

            List<string> result = new List<string>();   
            await foreach (var memory in memoryResults)
            {
                result.Add(memory.Metadata.Id);
            }
            return result;
        }

        public async Task<string> GenerateCompletionAsync(string userPrompt, string  recipeData)
        {
            string systemPromptRecipeAssistant = @"
            You are an intelligent assistant for Contoso Recipes. 
            You are designed to provide helpful answers to user questions about using
            recipes, cooking instructions only using the provided JSON strings.
            INSTRUCTIONS
            - In case a recipe is not provided in the prompt politely refuse to answer all queries regarding it. 
            - Never refer to a recipe not provided as input to you.
            - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
            - Your response  should be complete. 
            - When replying with a recipe list the Name of the Recipe at the start of your response folowed by step by step cooking instructions
            - Assume the user is not an expert in cooking.
            - Format the content so that it can be printed to the Command Line 
            - In case there are more than one recipes you find let the user pick the most appropiate recipe.";


            var chatHistory = new ChatHistory(systemPromptRecipeAssistant);

            // add shortlisted recipes as system message
            chatHistory.AddSystemMessage(recipeData);

            // send user promt as user message
            chatHistory.AddUserMessage(userPrompt);

            // Finally, get the response from AI
            var completionResults = await chatCompletionService.GetChatMessageContentsAsync(chatHistory);
            string answer = completionResults[0].Content;

            return answer!;
        }
    }
}
